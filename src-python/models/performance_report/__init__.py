"""Performance reports: what a session measured about itself, for one receiver.

A report says which PC parts ran which features and how late they were, so that advice
such as "this GPU cannot run these three at once" can rest on more than one PC. It holds
no text, no audio, no device or user names, no paths and nothing that follows a PC from
one start to the next. `schema.fault_of` is the whole list of what a report may hold; the
receiver checks the same list and refuses anything else.

This is not upstream VRCT's Aptabase telemetry (models/telemetry), which stays disabled.
Nothing here sends by itself: a caller with the user's setting has to ask.
"""
