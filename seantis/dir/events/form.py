# -- coding: utf-8 --

from five import grok

from plone.directives import form
from plone.z3cform.fieldsets import extensible

from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.schema import Choice
from zope.schema.interfaces import IContextSourceBinder
from zope.schema.vocabulary import SimpleVocabulary

from z3c.form import field, group
from z3c.form.browser.checkbox import CheckBoxFieldWidget
from z3c.form.browser.radio import RadioFieldWidget
from plone.formwidget.recurrence.z3cform.widget import RecurrenceWidget, ParameterizedWidgetFactory
from collective.z3cform.mapwidget.widget import MapFieldWidget

from plone.app.event.dx.behaviors import (
    IEventBasic,
    IEventRecurrence
)

from seantis.dir.events.interfaces import (
    ICoordinates,
    IEventsDirectory, 
    IEventsDirectoryItem
)

from seantis.dir.events import _

# I don't even..
class EventBaseForm(extensible.ExtensibleForm, form.AddForm):
    grok.baseclass()

class GeneralGroup(group.Group):
    label = _(u'Event')
    fields = field.Fields(IEventsDirectoryItem).select(
        'title', 'short_description', 'long_description', 'cat1', 'cat2'
    )
    fields += field.Fields(IEventBasic).select('start', 'end', 'whole_day')
    fields += field.Fields(IEventRecurrence).select('recurrence')

    def updateWidgets(self):
        super(GeneralGroup, self).updateWidgets()

        labels = self.context.labels()
        widgets = [w for w in self.widgets if w in labels]
        
        for widget in widgets:
            self.widgets[widget].label = labels[widget]

class LocationGroup(group.Group):
    label = _(u'Location')
    fields = field.Fields(ICoordinates).select('coordinates')
    fields += field.Fields(IEventsDirectoryItem).select(
        'locality', 'street', 'housenumber', 'zipcode', 'town'
    )

class InformationGroup(group.Group):
    label = _(u'Information')
    fields = field.Fields(IEventsDirectoryItem).select(
        'organizer', 'contact_name', 'contact_email',
        'contact_phone', 'prices', 'event_url', 'registration',
        'image', 'attachment_1', 'attachment_2'
    )

def available_categories(context, category):

    @grok.provider(IContextSourceBinder)
    def get_categories(ctx):
        terms = []

        encode = lambda s: s.encode('utf-8')

        for i, value in enumerate(context.suggested_values(category)):
            terms.append(SimpleVocabulary.createTerm(encode(value), hash(value), value))

        return SimpleVocabulary(terms)

    return get_categories

class EventSubmissionForm(EventBaseForm):
    grok.name('submit-event')
    grok.require('seantis.dir.events.SubmitEvents')
    grok.context(IEventsDirectory)

    template = ViewPageTemplateFile('templates/form.pt')

    groups = (GeneralGroup, LocationGroup, InformationGroup)
    enable_form_tabbing = True

    label = _(u'Event Submission Form')
    description = _(
        u'Send us your events and we will publish them on this website'
    )

    def updateFields(self):
        super(EventSubmissionForm, self).updateFields()

        # apply the recurrence widget
        recurrence = self.groups[0].fields['recurrence']
        recurrence.widgetFactory = ParameterizedWidgetFactory(
            RecurrenceWidget, start_field='start'
        )
        
        coordinates = self.groups[1].fields['coordinates']
        coordinates.widgetFactory = MapFieldWidget

        categories = (
            self.groups[0].fields['cat1'],
            self.groups[0].fields['cat2']
        )

        for category in categories:
            category.field.description = u''
            category.field.value_type = Choice(
                source=available_categories(self.context, category.__name__)
            )
        
        categories[0].widgetFactory = CheckBoxFieldWidget
        categories[1].widgetFactory = RadioFieldWidget