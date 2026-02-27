# Docker Customization

## Custom Certificate Authorities

Add custom certificate authorities to [/docker-customization/custom-ca-certificates](/docker-customization/custom-ca-certificates/) and they will be pull in to the system CAs during docker build.  Must be in .crt format.

## Custom pip.conf

Add customization as needed to [/docker-customization/pip.conf](/docker-customization/pip.conf).  This will be used during docker build.