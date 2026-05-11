# Plugin Duplication Bug Fix

**Version Implemented:** 0.229.001

## Issue Summary
When creating new plugins/actions, the system was duplicating all existing plugins instead of just adding the new one. This resulted in multiple copies of the same plugin appearing in the database.

## Root Cause
The issue was in the `save_personal_action()` function in `functions_personal_actions.py`. The function was always generating new UUIDs for plugins, even when updating existing ones:

```python
# Problematic code
if 'id' not in action_data or not action_data['id']:
    # Always generate UUID for ID to avoid conflicts
    action_data['id'] = str(uuid.uuid4())
```

When the frontend saved plugins (which sends ALL plugins back to the server), existing plugins without preserved IDs were treated as new plugins and assigned new UUIDs, creating duplicates.

## Solution Implemented
Modified the `save_personal_action()` function to:

1. **Check for existing plugins by name** before assigning IDs
2. **Preserve original IDs** when updating existing plugins
3. **Only generate new IDs** for truly new plugins

```python
# Fixed code
# Check if an action with this name already exists
existing_action = None
if 'name' in action_data and action_data['name']:
    existing_action = get_personal_action(user_id, action_data['name'])

# Preserve existing ID if updating, or generate new ID if creating
if existing_action:
    # Update existing action - preserve the original ID
    action_data['id'] = existing_action['id']
elif 'id' not in action_data or not action_data['id']:
    # New action - generate UUID for ID
    action_data['id'] = str(uuid.uuid4())
```

## Files Modified
- `functions_personal_actions.py` - Fixed the `save_personal_action()` function
- `config.py` - Version bump to 0.226.085

## Testing Results
✅ **Plugin creation works correctly** - New plugins get unique IDs  
✅ **Plugin updates preserve IDs** - No duplicates created when updating  
✅ **Multiple plugins work** - Can have multiple different plugins  
✅ **Deletion still works** - Individual plugins can be deleted properly  

## Impact
- **Resolved**: Plugin duplication when creating new actions
- **Maintained**: All existing functionality (create, update, delete)
- **Improved**: Database integrity and user experience

## Version
Fixed in version `0.226.085`
