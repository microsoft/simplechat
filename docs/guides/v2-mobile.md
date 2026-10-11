---
layout: page
title: "Use V2 on a phone"
description: "Find navigation, chat tools, and workspace documents without permanent sidebars narrowing your phone screen."
section: "Guides"
audience: user
version: "0.261.327"
---

## Find your work

Fixed/Implemented in version: **0.261.323**, recorded in
`application/single_app/config.py`.

On screens narrower than 768 pixels, **Open navigation** in the header gives
you the same destinations and account controls as the desktop rail. In Chat,
the drawer also contains conversation history and search. Close it with its
close button or by tapping the shaded page. Keyboard users can use Escape.
The page uses the full width while navigation is closed.

The notification bell stays in the header, so you do not need to open navigation
to check an unread notice. The classification banner remains above the interface
when your administrator has configured one.

## Keep page actions beside the title

Fixed/Implemented in version: **0.261.325**, recorded in
`application/single_app/config.py`.

Page headers keep navigation, title and actions in one horizontal band on phones.
The title and subtitle can remain stacked within their block and shorten with an
ellipsis when space is tight. One or two actions appear directly as icons with
accessible names and tooltips: workspace help, **Browse all groups**, directory
back/create controls, and **Refresh** do not require opening a menu.

Only headers with more than two available actions show **More actions** beside
the first action. The remaining actions open in an anchored overlay rather than
adding another header row. Escape returns focus to the opener; tapping outside or
choosing an action closes it. Hidden permission-gated actions and saving status
do not count toward this threshold. At 768 pixels and wider, desktop labels and
controls remain visible.

## Compose and inspect a chat

**Start a new chat** is directly available in the phone's chat header.
**Conversation actions** reveals the details, people, documents, contents, and
plan controls your current conversation supports in an anchored overlay. Opening
it does not increase the header height; choosing a control or pressing Escape
closes the overlay. **Start a new chat** and **Conversation actions** remain
directly available.

The composer keeps attachment, voice when enabled, and Send/Stop together.
**Chat tools** opens the existing model, agent, reasoning, and capability
controls. Closing this area does not clear your choices. When orchestration is
active, its approval mode appears in the collapsed summary.

Fixed/Implemented in version: **0.261.327**, recorded in
`application/single_app/config.py`.

Model, Agent, Prompt, Reasoning, Approval, and Orchestration model choices open
in floating menus anchored to their buttons, outside the scrolling tools area.
The menus open above or below according to available space, stay within the
visible viewport, and scroll long catalogs without cutting off choices. This
does not change the composer layout or replace the menu with a bottom sheet.
Tap an option to select it or tap outside to dismiss. Escape returns keyboard
focus to the opener; arrow keys and Home/End move through choices. Only one
picker opens at a time. Closing Chat tools or Manual controls closes their
picker without clearing the saved selection.

## Browse workspace documents

**Workspace sections** names your current section and opens the workspace's
permitted section links. It replaces the workspace icon rail on phones.
Group/public workspace selection stays visible; **Search** expands the
workspace search field on small phones.

Document rows prioritize readable names, processing/status information, and
selection. Tap the document name for its details, including secondary metadata.
Use Filters to narrow the list and the selection-aware action controls to work
with selected files. **Document view options** reveals sorting and the existing
view controls without keeping every toolbar row above your documents.
Available operations still depend on your workspace role;
a phone does not gain access to desktop-only permissions.

## Returning to a larger screen

The same pages and data are used at every size. At 768 pixels and wider, the
desktop rail returns with its saved collapse preference. Desktop document column
choices are preserved; resizing does not save a different view or reset your chat.

Actual Safari keyboard and home-indicator behavior should be checked on a real
device; browser viewport emulation alone cannot certify that experience.
