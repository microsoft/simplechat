---
applyTo: '**'
---
After a code change, update the version 

Example
Before Code Changes
app.config['VERSION'] = "0.224.072"

After Code Changes
app.config['VERSION'] = "0.224.073"

Only increment the third set of digits

Ensure the version is updated in the following files: 

config.py