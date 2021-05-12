# Cisco IOS Templates

This is a set of templates that can be used to build a config for a Cisco IOS[-XE] device.  The driver template is `all.j2`, and it
pulls in the others as needed.

The main use case for this work was to build a config for a stacked set of Catalyst 9500 switches, so the template fragments here
reflect that of an L2 switch.  However, they can be used as an example on how to add other IOS config bits.

## Example

In the `example-vars` directory you will find some sanitized variables that were used to fill in the variablized pieces of the Jinja2
template fragments.  If this directory is renamed `vars` (and the sanitized credential variables are fixed), the config can be
generated with the command:

```bash
build.py -r vars/sw-core all
```

