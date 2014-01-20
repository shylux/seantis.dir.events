import json
import urllib

from dateutil.parser import parse
from five import grok
from urllib import urlopen

from seantis.dir.events.dates import default_now
from seantis.dir.events.interfaces import (
    IExternalEventCollector,
    IExternalEventSourceSeantisJson
)


class EventsSourceSeantisJson(grok.Adapter):
    grok.context(IExternalEventSourceSeantisJson)
    grok.provides(IExternalEventCollector)

    def build_url(self):

        url = self.context.url.strip() + '?'
        # url += 'type=json&max=' + str(self.data.max_events) + '&' :TODO:
        url += 'type=json'
        if self.context.do_filter and (self.context.cat1 or self.context.cat2):
            url += '&filter=true'
            if self.context.cat1:
                cat = urllib.quote_plus(
                    self.context.cat1.strip().encode('utf-8')
                )
                url += '&cat1=' + cat
            if self.context.cat2:
                cat = urllib.quote_plus(
                    self.context.cat2.strip().encode('utf-8')
                )
                url += '&cat2=' + cat
        return url

    def fetch(self, json_string=None):

        if json_string is None:
            url = self.build_url()
            json_string = urlopen(url).read()
        events = json.loads(json_string)

        for event in events:

            cat1, cat2 = event.get('cat1'), event.get('cat2')
            cat1 = set(cat1) if cat1 is not None else set()
            cat2 = set(cat2) if cat2 is not None else set()

            if self.context.do_filter:
                if self.context.cat1:
                    if self.context.cat1:
                        if self.context.cat1 not in cat1:
                            continue
                    else:
                        continue
                if self.context.cat2:
                    if self.context.cat2:
                        if self.context.cat2 not in cat2:
                            continue
                    else:
                        continue

            e = {}
            e['fetch_id'] = self.context.url
            e['last_update'] = default_now()
            e['source_id'] = event['id']

            e['id'] = event.get('id')
            e['title'] = event.get('title')
            e['short_description'] = event.get('short_description')
            e['long_description'] = event.get('long_description')
            e['cat1'] = cat1
            e['cat2'] = cat2
            e['start'] = parse(event.get('start')).replace(tzinfo=None)
            e['end'] = parse(event.get('end')).replace(tzinfo=None)
            e['recurrence'] = event.get('recurrence')
            e['whole_day'] = event.get('whole_day')
            e['timezone'] = event.get('timezone')
            e['locality'] = event.get('locality')
            e['street'] = event.get('street')
            e['housenumber'] = event.get('housenumber')
            e['zipcode'] = event.get('zipcode')
            e['town'] = event.get('town')
            e['location_url'] = event.get('location_url')
            lon, lat = event.get('longitude'), event.get('latitude')
            e['longitude'] = str(lon) if lon is not None else None
            e['latitude'] = str(lat) if lon is not None else None
            e['organizer'] = event.get('organizer')
            e['contact_name'] = event.get('contact_name')
            e['contact_email'] = event.get('contact_email')
            e['contact_phone'] = event.get('contact_phone')
            e['prices'] = event.get('prices')
            e['event_url'] = event.get('event_url')
            e['registration'] = event.get('registration')
            e['image'] = event.get('image')
            e['attachment_1'] = event.get('attachment_1')
            e['attachment_2'] = event.get('attachment_2')
            e['submitter'] = event.get('submitter')
            e['submitter_email'] = event.get('submitter_email')

            yield e