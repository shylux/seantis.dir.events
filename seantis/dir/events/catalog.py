import transaction
from transaction.interfaces import ISavepointDataManager
from transaction._transaction import AbortSavepoint

from datetime import datetime, timedelta
from five import grok

from itertools import ifilter
from plone.app.event.ical.exporter import construct_icalendar
from plone.memoize import instance

from zope.interface import implements
from zope.annotation.interfaces import IAnnotations
from zope.lifecycleevent.interfaces import (
    IObjectMovedEvent,
    IObjectModifiedEvent,
    IObjectRemovedEvent
)
from Products.CMFCore.interfaces import IActionSucceededEvent

from seantis.dir.base.catalog import DirectoryCatalog
from seantis.dir.base.interfaces import IDirectoryCatalog
from seantis.dir.base.utils import previous_and_next, cached_property

from seantis.dir.events import utils
from seantis.dir.events import dates
from seantis.dir.events import recurrence
from seantis.dir.events.interfaces import (
    IEventsDirectory, IEventsDirectoryItem
)

from blist import sortedset


# this is just awful
# http://plone.293351.n2.nabble.com/Event-on-object-deletion-td3670562.html
# http://stackoverflow.com/questions/11218272/plone-reacting-to-object-removal
class ReindexDataManager(object):

    implements(ISavepointDataManager)

    def __init__(self, request, directory):
        self.request = request
        self.directory = directory
        self.transaction_manager = transaction.manager

    def tpc_begin(self, transaction):
        pass

    def tpc_finish(self, transaction):
        reindex_directory(self.directory)

    def tpc_abort(self, transaction):
        pass

    def commit(self, transaction):
        pass

    def abort(self, transaction):
        pass

    def tpc_vote(self, transaction):
        pass

    def sortKey(self):
        return id(self)

    def savepoint(self):
        """ Make it possible to enter a savepoint with this manager active. """
        return AbortSavepoint(self, transaction.get())


def attach_reindex_to_transaction(directory):
    request = getattr(directory, 'REQUEST', None)

    if request:
        transaction.get().join(ReindexDataManager(request, directory))


def may_reindex_directory(directory):
    if not directory:
        return False

    if hasattr(directory, '_v_fetching') and getattr(directory, '_v_fetching'):
        return False

    if not IEventsDirectory.providedBy(directory):
        return False

    return True


def reindex_directory(directory):
    if may_reindex_directory(directory):
        utils.get_catalog(directory).reindex()


@grok.subscribe(IEventsDirectoryItem, IObjectRemovedEvent)
def onRemovedItem(item, event):
    attach_reindex_to_transaction(event.oldParent)


@grok.subscribe(IEventsDirectoryItem, IObjectMovedEvent)
def onMovedItem(item, event):
    attach_reindex_to_transaction(event.oldParent)
    attach_reindex_to_transaction(event.newParent)


@grok.subscribe(IEventsDirectoryItem, IObjectModifiedEvent)
@grok.subscribe(IEventsDirectoryItem, IActionSucceededEvent)
def onModifiedItem(item, event):
    attach_reindex_to_transaction(item.get_parent())


class LazyList(object):

    def __init__(self, get_item, length):
        assert callable(get_item)

        self._get_item = get_item
        self.length = length
        self.cache = [get_item] * length

    def get_item(self, index):
        if self.cache[index] == self._get_item:
            self.cache[index] = self.cache[index](index)

        return self.cache[index]

    def __len__(self):
        return self.length

    def __getitem__(self, key):
        if isinstance(key, slice):
            return map(self.get_item, range(*key.indices(self.length)))

        if (key + 1) > self.length:
            raise IndexError

        return self.get_item(key)


class EventIndex(object):

    version = "1.0"

    def __init__(self, catalog, initial_index=None):
        self.catalog = catalog
        self.key = 'seantis.dir.events.eventindex'
        self.datekey = '%Y.%m.%d'

        # be careful here, there's self.index a property which gets
        # the index from the annotation. Initial_index is for debugging
        # only and must not overwrite an existing index otherwise.
        if initial_index is not None:
            self.index = initial_index

        if not self.index:
            self.reindex()

    @property
    def name(self):
        raise NotImplementedError

    def update(self, events):
        raise NotImplementedError

    def remove(self, events):
        raise NotImplementedError

    def reindex(self, events=[]):
        raise NotImplementedError

    @cached_property
    def annotations(self):
        return IAnnotations(self.catalog.directory, self.key)

    @property
    def index_key(self):
        return self.name + self.version

    def meta_key(self, key):
        return self.index_key + '_meta_' + key

    def get_index(self):
        return self.annotations.get(self.index_key, None)

    def set_index(self, value):
        self.annotations[self.index_key] = value

    index = property(get_index, set_index)

    def get_metadata(self, key):
        return self.annotations.get(self.meta_key(key), None)

    def set_metadata(self, key, value):
        self.annotations[self.meta_key(key)] = value

    def spawn_events(self, real, start=None, end=None):

        if not start or not end:
            start, end = map(dates.to_utc, dates.eventrange())

        return self.catalog.spawn(real, start, end)

    def event_by_id_and_date(self, id, date):

        real = self.catalog.query(id=id)[0].getObject()

        # there is currently no way to easily look up the event by date
        # if it has been split over dates already (which is what happens
        # when the events are indexed)

        # therefore we need to currently loop over all events to find the
        # right one. certainly this can be optimized.

        # however, tests on a 10k sites with 60% of all events being recurrent
        # indicate that it's not that big of a problem. spawning events is
        # quite fast and it only happens for 10 items per request

        # still, I would prefer some kind of lookup here

        min_date = date - timedelta(days=1)
        max_date = date + timedelta(days=1)

        for item in self.spawn_events([real], min_date, max_date):
            if dates.to_utc(dates.delete_timezone(item.local_start)) == date:
                return item

        assert False, "lookup for %s failed" % id


class EventOrderIndex(EventIndex):

    def __init__(self, catalog, state, initial_index=None):
        assert state in ('submitted', 'published', 'archived')
        self.state = state
        super(EventOrderIndex, self).__init__(catalog, initial_index)

    @property
    def name(self):
        return 'eventorder-%s' % self.state

    def identity(self, event):
        date = dates.delete_timezone(event.local_start)
        return '%s;%s' % (date.strftime('%y.%m.%d-%H:%M'), event.id)

    def identity_id(self, identity):
        return identity[15:]

    def identity_date(self, identity):
        return dates.to_utc(datetime.strptime(identity[:14], '%y.%m.%d-%H:%M'))

    def event_by_identity(self, identity):

        id = self.identity_id(identity)
        date = self.identity_date(identity)

        return self.event_by_id_and_date(id, date)

    def reindex(self):

        events = self.catalog.query(review_state=self.state)
        self.index = sortedset()

        self.update(events)
        self.generate_metadata()

    def update(self, events):
        if events:
            self.remove(events)

        managed = (e for e in events if e.review_state == self.state)

        for event in self.spawn_events(managed):
            self.index.add(self.identity(event))

    def remove(self, events):
        assert events

        ids = [r.id for r in events]
        stale = set(i for i in self.index if self.identity_id(i) in ids)

        self.index = sortedset(self.index - stale)

    def generate_metadata(self):
        """Creates a metaindex, indexing the date positions by date.
        For example:

        Events:
            0 -> 01.01.2012
            1 -> 05.01.2012
            2 -> 06.01.2012

        Resulting metaindex:
            01.01.2012 -> 0
            02.01.2012 -> 1
            03.01.2012 -> 1
            04.01.2012 -> 1
            05.01.2012 -> 1
            06.01.2012 -> 2

        The idea is for every possible date between the first event
        and the last event to point to an event in the index. This allows
        for fast pagination using slicing.

        """

        if not self.index:
            if self.get_metadata('dateindex'):
                self.set_metadata('dateindex', None)
            return

        dt = lambda i: i if i is None else self.identity_date(i).date()

        keydates = {}

        # set the key positions (first occurrence of each date)
        for ix, date in enumerate(map(dt, self.index)):
            if date not in keydates:
                keydates[date] = ix

        # fill the gaps
        dateindex = {}
        for prev, curr, next in previous_and_next(sorted(keydates.keys())):
            if prev is None:
                continue
            if prev == curr:
                continue

            for date in dates.days_between(prev, curr):
                dateindex[date] = keydates[curr]

        # merge
        dateindex.update(keydates)

        self.set_metadata('dateindex', dateindex)

    def by_range(self, start, end):

        if not start and not end:
            return self.index

        if not self.index:
            return []

        first_date = self.identity_date(self.index[0])
        last_date = self.identity_date(self.index[-1])

        if not dates.overlaps(first_date, last_date, start, end):
            return []

        dateindex = self.get_metadata('dateindex')

        # use whatever timezone is given, because a search for a range cannot
        # be normalized, since the day of this search is not really a concept
        # that exists globally, everyone calls a different utc time a day
        start = (start or first_date).date()
        end = (end or last_date).date()

        if start <= first_date.date():
            startrange = 0
        else:
            startrange = dateindex[start]

        if end >= last_date.date():
            endrange = len(self.index)
        else:
            endrange = dateindex[end + timedelta(days=1)]

        return self.index[startrange:endrange]

    def limit_to_subset(self, index, subset):

        if not subset:
            return index

        ids = set(brain.id for brain in subset)
        return filter(lambda i: self.identity_id(i) in ids, index)

    def lazy_list(self, start, end, subset=None):
        subindex = self.by_range(start, end)
        subindex = self.limit_to_subset(subindex, subset)
        get_item = lambda i: self.event_by_identity(subindex[i])

        return LazyList(get_item, len(subindex))


class EventsDirectoryCatalog(DirectoryCatalog):

    grok.context(IEventsDirectory)
    grok.provides(IDirectoryCatalog)

    def __init__(self, *args, **kwargs):
        self._daterange = dates.default_daterange
        self._state = 'published'

        self.subset = None

        super(EventsDirectoryCatalog, self).__init__(*args, **kwargs)

        self.ix_submitted = self.index_for_state('submitted')
        self.ix_published = self.index_for_state('published')
        self.indices = dict(
            submitted=self.ix_submitted, published=self.ix_published
        )

    def index_for_state(self, state):
        return EventOrderIndex(self, state)

    def reindex(self):
        for ix in self.indices.values():
            ix.reindex()

    @property
    def submitted_count(self):
        """ Returns the submitted count depending on the current date filter
        but independent of the current state filter.

        This needs to loop through all elements again so use only if needed.
        """

        results = self.catalog(
            path={'query': self.path, 'depth': 1},
            object_provides=IEventsDirectoryItem.__identifier__,
            review_state=('submitted', )
        )

        submitted_count = 0

        items = []
        for item in results:
            if self.directory.allow_action('publish', item):
                items.append(item)

        for spawn in self.spawn(items):
            submitted_count += 1

        return submitted_count

    def get_daterange(self):
        return self._daterange

    @instance.clearafter
    def set_daterange(self, range):
        assert dates.is_valid_daterange(range), "invalid date range %s" % range
        self._daterange = range

    daterange = property(get_daterange, set_daterange)

    def get_state(self):
        return self._state

    @instance.clearafter
    def set_state(self, state):
        # as an added security measure it is not yet possible to
        # query for previewed events as they should only be availble
        # to the user with the right token (see form.py)
        assert state in ('submitted', 'published', 'archived')

        self._state = state

    state = property(get_state, set_state)

    def sortkey(self):
        return lambda i: i.start

    def query(self, review_state=None, **kwargs):
        review_state = review_state or self.state
        results = self.catalog(
            path={'query': self.path, 'depth': 1},
            object_provides=IEventsDirectoryItem.__identifier__,
            review_state=review_state,
            **kwargs
        )

        return results

    def spawn(self, realitems, start=None, end=None):
        if not all((start, end)):
            start, end = getattr(dates.DateRanges(), self._daterange)

        for item in realitems:
            for occurrence in recurrence.occurrences(item, start, end):
                for split in recurrence.split_days(occurrence):
                    if dates.overlaps(start, end, split.start, split.end):
                        yield split

    def hide_blocked(self, realitems):
        """ Returns a generator filtering real items, with the submitted items
        which the user can see but not publish left out.

        As this could be reeealy slow we do a bit of a shortcut by only
        checking for the publish action right on the item. The guard is
        in place anyway, so the user will at worst see an item with which
        he can't do anything.

        """

        if self.state != 'submitted':
            return (r for r in realitems)

        key = lambda i: i.review_state != 'submitted' \
            or self.directory.allow_action('publish', i)

        return ifilter(key, realitems)

    @property
    def lazy_list(self):
        start, end = getattr(dates.DateRanges(), self.daterange)
        return self.indices[self.state].lazy_list(start, end, self.subset)

    @instance.memoize
    def all_items(self):
        real = super(EventsDirectoryCatalog, self).items()
        return sorted(self.spawn(self.hide_blocked(real)), key=self.sortkey())

    def filter(self, term):
        nonempty_terms = [t for t in term.values() if t != u'!empty']

        if len(nonempty_terms) == 0:
            return self.items()

        self.subset = super(EventsDirectoryCatalog, self).filter(term)
        return sorted(
            self.spawn(self.hide_blocked(self.subset)), key=self.sortkey()
        )

    def search(self, text):
        self.subset = super(EventsDirectoryCatalog, self).search(text)
        return sorted(
            self.spawn(self.hide_blocked(self.subset)), key=self.sortkey()
        )

    def calendar(self, search=None, filter=None):
        if search:
            items = super(EventsDirectoryCatalog, self).search(search)
        elif filter:
            items = super(EventsDirectoryCatalog, self).filter(filter)
        else:
            items = super(EventsDirectoryCatalog, self).items()

        return construct_icalendar(self.directory, items)
