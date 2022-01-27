#!/usr/bin/python3
"""This reads a set of templates and parameters and builds JunOS configuration."""
#
# In order to make this easy to use, there are a number of
# conventions:
#  - by default, configuration parameters are in ./vars
#  - config parameters are in .yaml files. They are all combined / concatenated
#  - the exception to this is files called <device>_device_specific.yaml.
#    - there are only applied to <device>
#
# Templates are stored in the main directory, and are written in Jinja2.
#
# Copyright 2018 Warren Kumari <warren@kumari.net>


from optparse import OptionParser
import glob
import os
import sys
import yaml
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

from jinja2 import nodes, Environment, FileSystemLoader, StrictUndefined
from jinja2.ext import Extension
from jinja2.exceptions import TemplateRuntimeError

# Debug. If True then we print more stuff.
DEBUG = False

class Error(Exception):
    """Generic error."""


class TemplateError(Error):
    """This template throws this sort of error...."""

class RaiseExtension(Extension):
    '''Allows us to raise an exception and return a message.'''

    ## Example:
    #  {%- if cup == "empty" %} {% raise "Need more coffee" %}

    # This is our keyword(s):
    tags = set(['raise'])

    # See also: jinja2.parser.parse_include()
    # https://stackoverflow.com/questions/21778252/how-to-raise-an-exception-in-a-jinja2-macro
    def parse(self, parser):
        lineno = next(parser.stream).lineno

        # Extract the message from the template
        message_node = parser.parse_expression()

        return nodes.CallBlock(
            self.call_method('_raise', [message_node], lineno=lineno),
            [], [], [], lineno=lineno
        )

    def _raise(self, msg, caller):
        raise TemplateRuntimeError(msg)

def debug(msg):
    """Iff DEBUG then we print message."""
    if opts.debug:
        sys.stderr.write('\033[94mDEBUG: %s\n\033[0m' % msg)


def log(msg):
    """If --verbose, print the message"""
    if opts.verbose:
        sys.stderr.write('\033[92mLOG: %s\n\033[0m' % msg)


def abort(msg):
    """Print error message and abort"""
    sys.stderr.write('\033[91mABORT: %s\n\033[0m' % msg)
    sys.exit(-1)

def output(msg):
    """Simply prints the message provided."""
    sys.stdout.write('\033[93m%s\n\033[0m' % msg)

def parse_options():
    """Parses the command line options."""
    global opts, args
    usage = """%prog [-v, -d, -c foo, -r rtr1]

This reads a set of templates and parameters and builds JunOS configuration.

In order to make this easy to use, there are a number of
conventions:
  - by default, configuration parameters are in ./vars
  - config parameters are in .yaml files. They are all combined / concatenated
  - the exception to this is files called <device>_device_specific.yaml.
    - there are only applied to <device>

 Templates are stored in the main directory, and are written in Jinja2.

  This does minimal error checking.

  Example:
      %prog -r rtr1 all.j2
         Reads the YAML files in ./vars/*, and rtr1_device_specific.yaml
         It takes the paramters in these, and puts then into the templates in
         all.j2.

  """

    options = OptionParser(usage=usage)
    options.add_option('-v', '--verbose', dest='verbose',
                       action='store_true',
                       default=False,
                       help='Be more verbose in output.')
    options.add_option('-d', '--debug', dest='debug',
                       action='store_true',
                       default=DEBUG,
                       help='Debug output.')
    options.add_option('-c', '--config_dir', dest='config_dir',
                       default="./vars",
                       help='Directory containing config variables (.yaml')
    options.add_option('-r', '--router', dest='device',
                       default="",
                       help='Make config for this specific device.')
    options.add_option('-t', '--templates', dest='template_dir',
                       default=".",
                       help='Directory containing templates. Default "."')
    options.add_option('-p', '--platform', dest='platform',
                       default="junos",
                       help='Directory containing *base* templates. Default "junos"')

    (opts, args) = options.parse_args()
    if not args:
        options.print_help()
        abort ("\nYou also need to supply a template name - perhaps all.j2 ?")
    if opts.device.startswith ('vars/') or opts.device.startswith ('./'):
        log ('You supplied a path to the device name  - cleaning up')
        opts.device = opts.device.replace('./', '')
        opts.device = opts.device.replace('vars/', '')
        opts.device = opts.device.replace('_device_specific.yaml', '')
    return opts, args


def combine_config_data(base, new, filename):
    """This merges the new config data into the base.

    This takes 2 dictionaries and merges them, aborting on error.

    Returns:
        Dictionary of base + new
        """
    for key in new.keys():
        if key in base:
            abort("The variable \"%s\" already exists in %s" % (key, filename))
    return base.update(new)


def read_config_data(path):
    """Reads the config data from the YAML files.

    This returns a dictionary of device specific config, and a dictionary of
    everything else.
    Abort on duplicate keys.

    Args:
        path: A String containing templates dir (vars dir is a subdir of this).

    Returns:
        devices: {"rtra": {"hostname:": "foo"}, "rtrb": ...}
        config_data: {"syslog": "services.meeting..", ...}
    """
    devices = {}
    config_data = {}
    for filename in glob.glob(path + "/*.yaml"):
        #debug ("Trying to read: %s" % filename)
        new = yaml.load(open(filename), Loader=Loader)
        if new is None:
            abort("Could not load configuration from %s. Invalid YAML or empty file.")
        debug ("Read %s elements from %s" % (len(new), filename))

        # Is this a device specific config?
        if '_device_specific.yaml' in filename:
            # Extract just the device name
            base=os.path.basename(filename)
            device_name = os.path.splitext(base)[0]
            device_name = device_name.replace('_device_specific','')
            # And add it (and its config) to the devices dictionary.
            devices[device_name] = new
        else:
            combine_config_data(config_data, new, filename)
    debug ("Config data length: %s" % len(config_data))
    return (devices, config_data)


def open_template(path, name):
    """Opens the named template

    Returns:
        Jinja2 template
    """

    # If we are called with a file called <something.yaml> (e.g because of
    # tab completion), strip it to get the base name.
    base = os.path.basename(name)
    name = os.path.splitext(base)[0]

    # Script dir
    script_dir = os.path.dirname(os.path.realpath(sys.argv[0]))

    env = Environment(loader = FileSystemLoader([path,
            os.path.join(script_dir, opts.platform)]),
        trim_blocks=False,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        extensions=[RaiseExtension])
    template = env.get_template(name + '.j2')
    return template


def render (devices, template, config_data):
    """Renders the template with the provided config data.

    Basically a wrapper around template.render

    Returns:
        prints filled in template
    """
    if opts.device:
        opts.device=opts.device.replace('./', '/', 1)
        debug("Device we are building for: %s" % opts.device)
        if opts.device and opts.device in devices.keys():
            # Add the device specific bits to the config.
            device_specific = devices[opts.device]
            if not device_specific:
                abort("The length of the device specific data for %s is 0. Perhaps empty file?!" % opts.device)
            combine_config_data (config_data, device_specific, opts.device)
        else:
            abort("Couldn't find a _device_specific.yaml for %s" % opts.device)

    rendered = template.render(config_data)
    print(rendered)


def main():
    """pylint FTW"""
    (device_config, config_data) = read_config_data(opts.config_dir)
    template = open_template(opts.template_dir, args[0])
    render (device_config, template, config_data)


if __name__ == "__main__":
    parse_options()
    main()
    sys.exit(0)
