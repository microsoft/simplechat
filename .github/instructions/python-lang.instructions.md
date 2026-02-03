---
applyTo: '**/*.py'
---

# Python Language Guide

- All files MUST start with a comment of the file name. Ex: `# functions_personal_agents.py`

## Rule: Follow Standard Python Conventions

- Standard python conventions, such as the use of snake case, must be followed.

## Rule: Imports Must Be Organized and at the Top

- IMPORTANT: Imports MUST be grouped at the top of the document after the module docstring, unless otherwise indicated by the code writer or for performance reasons in which case the import should be as close as possible to the usage with a comment explaining why the import is not at the top of the file.

## Rule: Indentation, Logging, and Decorators
- Use 4 spaces per indentation level. No tabs.

- Code and definitions should occur after the imports block.

- All logging should used tag based prefixes. Ex: [GPTClient] or [SKLoader] to identify the source of the log message and make it easier to trace. Tags should be enclosed in square brackets. Tags should be generalized to the operation that is occurring. Any existins logging that is missing tags should have tags added.

- Prefer using ```log_event``` from functions_appinsights.py for production-type logging activites.

- Use ```debug_print``` from functions_debug.py for debug logging purposes. All method, calls, warnings and errors should be debug_logged. 

- Files with routes MUST import ```from swagger_wrapper import swagger_route, get_auth_security``` and use the ```@swagger_route(security=get_auth_security())``` decorator for all route functions.

- Unless otherwise indicated, all routes MUST include ```@login_required``` decorator. 