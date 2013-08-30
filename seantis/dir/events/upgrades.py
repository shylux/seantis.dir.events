import logging
log = logging.getLogger('seantis.dir.events')

from Products.CMFCore.utils import getToolByName
from zope.component.hooks import getSite

from plone.app.theming.utils import (
    applyTheme,
    getOrCreatePersistentResourceDirectory
)

from seantis.dir.base.interfaces import IDirectoryCatalog
from seantis.dir.base.upgrades import (
    add_behavior_to_item,
    reset_images_and_attachments
)

from seantis.dir.events.submission import EventSubmissionData
from seantis.dir.events.interfaces import (
    IEventsDirectory,
    IEventsDirectoryItem
)


def setup_indexing(context):
    setup = getToolByName(context, 'portal_setup')

    profile = 'profile-seantis.dir.events:default'
    setup.runImportStepFromProfile(profile, 'typeinfo')
    setup.runImportStepFromProfile(profile, 'catalog')

    # reindex everything
    catalog = getToolByName(context, 'portal_catalog')
    catalog.clearFindAndRebuild()

    # rebuild eventindexes
    directories = catalog(object_provides=IEventsDirectory.__identifier__)

    for directory in directories:

        directory_catalog = IDirectoryCatalog(directory.getObject())
        directory_catalog.reindex()


def upgrade_1000_to_1001(context):
    add_behavior_to_item(context, 'seantis.dir.events', IEventsDirectoryItem)
    reset_images_and_attachments(
        context,
        (IEventsDirectory, IEventsDirectoryItem),
        ['image', 'attachment_1', 'attachment_2']
    )


def upgrade_1001_to_1002(context):

    # 1002 untangles the dependency hell that was default <- sunburst <- izug.
    # Now, sunburst and izug.basetheme both have their own profiles.

    # Since the default profile therefore has only the bare essential styles
    # it needs to be decided on upgrade which theme was used, the old css
    # files need to be removed and the theme profile needs to be applied.

    # acquire the current theme
    skins = getToolByName(context, 'portal_skins')
    theme = skins.getDefaultSkin()

    # find the right profile to use
    profilemap = {
        'iZug Base Theme': 'izug_basetheme',
        'Sunburst Theme': 'sunburst'
    }

    if theme not in profilemap:
        log.info("Theme %s is not supported by seantis.dir.events" % theme)
        profile = 'default'
    else:
        profile = profilemap[theme]

    # remove all existing event stylesheets
    css_registry = getToolByName(context, 'portal_css')
    stylesheets = css_registry.getResourcesDict()
    ids = [i for i in stylesheets if 'resource++seantis.dir.events.css' in i]

    map(css_registry.unregisterResource, ids)

    # remove the old diazo theme and disable theming for now
    themes = getOrCreatePersistentResourceDirectory()
    to_delete = [
        'izug.seantis.dir.events.theme',
        'vbeo.seantis.dir.events.theme'
    ]
    for theme in to_delete:
        try:
            del themes[theme]
        except KeyError:
            continue

    applyTheme(None)

    setup = getToolByName(context, 'portal_setup')

    # reapply the chosen profile
    setup.runAllImportStepsFromProfile(
        'profile-seantis.dir.events:%s' % profile
    )

    # there are currently two installations, bern and zug
    if getSite().id == 'vbeo':
        setup.runAllImportStepsFromProfile(
            'profile-vbeo.seantis.dir.events:default'
        )
    else:
        setup.runAllImportStepsFromProfile(
            'profile-izug.seantis.dir.events:default'
        )


def upgrade_1002_to_1003(context):
    # the new plone.formwidget.recurrence release introduced gs profiles which
    # need to be loaded on existing sites

    setup = getToolByName(context, 'portal_setup')
    setup.runAllImportStepsFromProfile(
        'profile-plone.formwidget.recurrence:default'
    )


def upgrade_1003_to_1004(context):
    # import new javascript
    setup = getToolByName(context, 'portal_setup')
    setup.runImportStepFromProfile(
        'profile-seantis.dir.events:default', 'jsregistry'
    )
    setup.runImportStepFromProfile(
        'profile-seantis.dir.events:default', 'cssregistry'
    )


def upgrade_1004_to_1005(context):
    # adds a new behvaior
    setup = getToolByName(context, 'portal_setup')
    setup.runImportStepFromProfile(
        'profile-seantis.dir.events:default', 'typeinfo'
    )

    # add underscore.js
    setup.runAllImportStepsFromProfile(
        'profile-collective.js.underscore:default'
    )

    # upgrade javascript
    setup.runImportStepFromProfile(
        'profile-seantis.dir.events:default', 'jsregistry'
    )

    # guess the submission data for the existing events. This does
    # not actually lead to a change of the event dates, it just opens
    # the possiblity to do so by manually editing and saving the event
    catalog = getToolByName(context, 'portal_catalog')
    brains = catalog(object_provides=IEventsDirectoryItem.__identifier__)

    h = 60 * 60

    for brain in brains:
        # don't acquire through interface as that would require more reindexing
        event = brain.getObject()
        submission = EventSubmissionData(event)

        if (event.end - event.start).total_seconds() < 24 * h:
            submission.submission_date_type = ['date']
            submission.submission_date = event.local_start.date()
            submission.submission_start_time = event.local_start.time()
            submission.submission_end_time = event.local_end.time()
            submission.submission_recurrence = event.recurrence
        else:
            # eventual recurrence is lost here, it's no longer possible
            # to have recurring events which last for days
            submission.submission_date_type = ['range']
            submission.submission_range_start_date = event.local_start.date()
            submission.submission_range_end_date = event.local_end.date()
            submission.submission_range_start_time = event.local_start.time()
            submission.submission_range_end_time = event.local_end.time()

        # the guidle import had bug where whole_day was not set at all times
        if hasattr(event, 'whole_day'):
            submission.submission_whole_day = event.whole_day
        else:
            submission.submission_whole_day = False


def upgrade_1005_to_1006(context):
    setup = getToolByName(context, 'portal_setup')

    profiles = [
        'teamraum', 'sunburst', 'izug_basetheme'
    ]

    for profile in profiles:
        full_profile = 'profile-seantis.dir.events:{}'.format(profile)

        if setup.getProfileImportDate(full_profile):
            setup.runImportStepFromProfile(full_profile, 'cssregistry')


def upgrade_1006_to_1007(context):
    setup = getToolByName(context, 'portal_setup')

    # For some reason this profile was not imported on some older events
    # installations. This leads to exceptions.
    setup.runImportStepFromProfile(
        'profile-plone.app.event:default', 'browserlayer'
    )

def upgrade_1007_to_1008(context):
    setup = getToolByName(context, 'portal_setup')

    # add collective.geo.behaviour
    setup.runAllImportStepsFromProfile(
        'profile-collective.geo.behaviour:default'
    )

    add_behavior_to_item(context, 'seantis.dir.events', IEventsDirectoryItem)