#!/usr/bin/env python3
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
import pprint
import sys
import yaml

from jinja2 import nodes, Environment, FileSystemLoader, StrictUndefined, Template
from jinja2.ext import Extension
from jinja2.exceptions import TemplateRuntimeError

# Debug. If True then we print more stuff.
DEBUG = False


class Error(Exception):
    """Generic error."""


class TemplateError(Error):
    """This template throws this sort of error...."""


class RaiseExtension(Extension):
    """Allows us to raise an exception and return a message."""

    # Example:
    #  {%- if cup == "empty" %} {% raise "Need more coffee" %}

    # This is our keyword(s):
    tags = set(["raise"])

    # See also: jinja2.parser.parse_include()
    # https://stackoverflow.com/questions/21778252/how-to-raise-an-exception-in-a-jinja2-macro
    def parse(self, parser):
        lineno = next(parser.stream).lineno

        # Extract the message from the template
        message_node = parser.parse_expression()

        return nodes.CallBlock(
            self.call_method("_raise", [message_node], lineno=lineno),
            [],
            [],
            [],
            lineno=lineno,
        )

    def _raise(self, msg, caller):
        raise TemplateRuntimeError(msg)


def debug(msg):
    """Iff DEBUG then we print message."""
    if opts.debug:
        sys.stderr.write("\033[94mDEBUG: %s\n\033[0m" % msg)


def log(msg):
    """If --verbose, print the message"""
    if opts.verbose or opts.debug:
        sys.stderr.write("\033[92mLOG: %s\n\033[0m" % msg)


def warn(msg):
    """Print warning message"""
    sys.stderr.write("\033[91mWARN: %s\n\033[0m" % msg)


def abort(msg):
    """Print error message and abort"""
    sys.stderr.write("\033[91mABORT: %s\n\033[0m" % msg)
    sys.exit(-1)


def output(msg):
    """Simply prints the message provided."""
    sys.stdout.write("\033[93m%s\n\033[0m" % msg)


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
    options.add_option(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        default=False,
        help="Be more verbose in output.",
    )
    options.add_option(
        "-d",
        "--debug",
        dest="debug",
        action="store_true",
        default=DEBUG,
        help="Debug output.",
    )
    options.add_option(
        "-c",
        "--config_dir",
        dest="config_dir",
        default=["./vars"],
        action="append",
        help="Directory containing config variables (in .yaml files).  Multiple config directories can be passed.",
    )
    options.add_option(
        "-r",
        "--router",
        dest="device",
        default="",
        help="Make config for this specific device.",
    )
    options.add_option(
        "-t",
        "--templates",
        dest="template_dir",
        default=".",
        help='Directory containing templates. Default "."',
    )
    options.add_option(
        "-p",
        "--platform",
        dest="platform",
        default="junos",
        help='Directory containing *base* templates. Default "junos"',
    )
    options.add_option(
        "-m",
        "--map",
        dest="map_filename",
        default="",
        help='File containing vlan map. Default ""',
    )
    options.add_option(
        "-i",
        "--interface_template",
        dest="interface_template",
        default="",
        help="File containing interface template. REQUIRED if --map is used.",
    )
    options.add_option(
        "-O",
        "--allow_override",
        dest="allow_override",
        action="store_true",
        default=False,
        help="Allow variables from more specific files to override base variables (default: False)",
    )

    (opts, args) = options.parse_args()
    if not args:
        options.print_help()
        abort("\nYou also need to supply a template name - perhaps all.j2 ?")
    if opts.device.startswith("vars/") or opts.device.startswith("./"):
        log("You supplied a path to the device name  - cleaning up")
        opts.device = opts.device.replace("./", "")
        opts.device = opts.device.replace("vars/", "")
        opts.device = opts.device.replace("_device_specific.yaml", "")
    if opts.map_filename and not opts.interface_template:
        abort("You must supply an interface template if you are using a vlan map.")
    return opts, args


def combine_config_data(base, new, filename, override=False):
    """This merges the new config data into the base.

    This takes 2 dictionaries and merges them, aborting on error.

    Returns:
        Dictionary of base + new
    """
    if not override:
        for key in new.keys():
            if key in base:
                abort('The variable "%s" loaded from %s already exists in the config data.' % (key, filename))
    return base.update(new)


def build_interface_from_template(filename, interface, vlan_name, desc="No description"):
    """This builds a default interface.

    This takes a filename to an interface template and an interface name, and
    returns a dictionary of the interface.

    Returns:
        Dictionary of interface, built from the template.
    """
    with open(filename) as f:
        template = Template(f.read())
    if template is None:
        abort("Could not load interface template from %s. Invalid Jinja or empty file." % filename)
    rendered = template.render(interface=interface, vlan_name=vlan_name, desc=desc)
    int_dict = yaml.safe_load(rendered)
    return int_dict


def read_config_data(path, vlan_map, override=False):
    """Reads the config data from the YAML files.

    This returns a dictionary of device specific config, and a dictionary of
    everything else.
    Abort on duplicate keys.

    Args:
        path: A String containing templates dir (vars dir is a subdir of this).
        vlan_map: A dictionary containing the vlan map. A vlan_map is a dictionary
                  of device -> vlan -> interface -> description.

    Returns:
        devices: {"rtra": {"hostname:": "foo"}, "rtrb": ...}
        config_data: {"syslog": "services.meeting..", ...}
    """
    devices = {}
    config_data = {}
    for p in path:
        for filename in glob.glob(p + "/*.yaml"):
            new = yaml.safe_load(open(filename))
            if new is None:
                abort("Could not load configuration from %s. Invalid YAML or empty file." % filename)
            debug("Read %s elements from %s" % (len(new), filename))

            # Is this a device specific config?
            if "_device_specific.yaml" in filename:
                # Extract just the device name
                base = os.path.basename(filename)
                device_name = os.path.splitext(base)[0]
                device_name = device_name.replace("_device_specific", "")
                # And add it (and its config) to the devices dictionary.
                if device_name not in devices:
                    devices[device_name] = new
                else:
                    combine_config_data(devices[device_name], new, filename, override)
            else:
                combine_config_data(config_data, new, filename, override)

    # If we have a vlan map, we create interface configs from it, and add them
    # to the device specific config.
    #
    # NOTE: This section seems somewhat Juniper specific....
    if vlan_map:
        # E.g:  {'sw1': {'ge-1/1/1': {'To bob': 'VLAN2'}, 'ge-1/2/2': {'To fred': 'VLAN99'}}
        for device in vlan_map.keys():

            if device not in devices:
                abort("Couldn't find a _device_specific.yaml for %s. Cannot continue." % device)
            else:
                # Check if the device has an "interfaces" key, and if not, add it.
                if "interfaces" not in devices[device]:
                    abort("Looks like %s had no interfaces. Cowardly refusing to continue..." % device)
                    devices[device]["interfaces"] = {}

                # e.g: {'eth1': 'AUTH-SERVERS', 'eth2': 'AUTH-SERVERS'}
                for interface, vlan_desc in vlan_map[device].items():
                    # Check if the interface is already defined in the device specific config.
                    # This is a list of dictionaries, so we need to iterate over it.
                    for i in devices[device]["interfaces"]:
                        if interface in i["interface"]:
                            abort(
                                "Looks like %s already had an interface %s. You cannot define it in both _device_specific and vlan map."
                                % (device, interface)
                            )
                    if len(vlan_desc) != 1:
                        abort(
                            "%s had more than one VLAN defined for interface %s in the VLAN Map - %s. This is not yet supported."
                            "" % (device, interface, vlan_desc)
                        )
                    (desc, vlan) = vlan_desc.popitem()
                    built = build_interface_from_template(opts.interface_template, interface, vlan, desc)
                    devices[device]["interfaces"].append(built)
    return (devices, config_data)


def read_vlan_map(map_filename):
    """
    Reads the vlan map from the file and converts it into a device specific map.
    Basically, this pivots the config from VLAN -> device into device -> VLAN.

    Args:
        map_file: A String containing the filename of the vlan map.
    """
    # The format of the vlan map is in the
    device_map = {}
    with open(map_filename, "r") as map_file:
        map_file = yaml.safe_load(map_file)
        if map_file is None:
            abort("Could not load interface map from %s. Invalid YAML or empty file." % map_filename)
        debug("Read %s elements from %s" % (len(map_file), map_filename))

    # vlan_map is VLAN -> device -> Interface, and we need to pivot it to device -> VLAN -> Interface
    for vlan in map_file["mapping"]:
        vlan_name = vlan["name"]
        for device in vlan["devices"]:
            if device not in device_map:
                device_map[device] = {}
            # A list of interfaces, desc
            for interface, desc in vlan["devices"][device].items():
                if interface not in device_map[device]:
                    device_map[device][interface] = {}
                device_map[device][interface][desc] = vlan_name
    return device_map
    # Now I will try do this again using a template instead.


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

    env = Environment(
        loader=FileSystemLoader([path, os.path.join(script_dir, opts.platform)]),
        trim_blocks=False,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        extensions=[RaiseExtension, "jinja2.ext.do"],
    )
    template = env.get_template(name + ".j2")
    return template


def render(devices, template, config_data):
    """Renders the template with the provided config data.

    Basically a wrapper around template.render

    Returns:
        prints filled in template
    """
    if opts.device:
        opts.device = opts.device.replace("./", "/", 1)
        debug("Device we are building for: %s" % opts.device)
        if opts.device and opts.device in devices.keys():
            # Add the device specific bits to the config.
            device_specific = devices[opts.device]
            if not device_specific:
                abort("The length of the device specific data for %s is 0. Perhaps empty file?!" % opts.device)
            combine_config_data(config_data, device_specific, opts.device)
        else:
            abort("Couldn't find a _device_specific.yaml for %s" % opts.device)

    rendered = template.render(config_data, trim_blocks=True, lstrip_blocks=True)
    print(rendered)


def main():
    """pylint FTW"""
    vlan_map = {}
    if opts.map_filename:
        vlan_map = read_vlan_map(opts.map_filename)
    (device_config, config_data) = read_config_data(opts.config_dir, vlan_map, opts.allow_override)
    template = open_template(opts.template_dir, args[0])
    render(device_config, template, config_data)


if __name__ == "__main__":
    parse_options()
    main()
    sys.exit(0)
