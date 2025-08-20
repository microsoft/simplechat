---
applyTo: '**'
---
After a code change, update the version 

Example
Before Code Changes
app.config['VERSION'] = '0.224.016'

After Code Changes
app.config['VERSION'] = '0.224.017'

Only increment the third set of digits

Example
Before Code Changes
app.config['VERSION'] = '0.224.099'

After Code Changes
app.config['VERSION'] = '0.224.100'

Ensure the version is updated in the following files: 

config.py