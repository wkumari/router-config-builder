#  Router Config Builder

[TOC]

This reads a set of variables (usually in `./vars/*.yaml`) and templates and builds configurations. This was originally written to build Juniper router configs, but has been used to do all sorts of templating, etc.

The variables are written in [YAML](https://learn.getgrav.org/15/advanced/yaml), and the configlets (templates) are written in [Jinja2](http://jinja.pocoo.org).

The general design that we update the variables files with the new information for each meeting (interface configs, BGP configs, etc), run the `build.py` script, and copy and paste the resulting config into the device (now actually deployed with Ansible). The current set of templates builds JunOS, but could equally build Ubiquiti, Cisco, Arista, etc.



This was originally written to build JunOS router configs for the IETF Meeting network. We kept running into issues where the config would slowly drift over the course of the meeting. When we'd unpack the gear at the start of the next meeting we'd have to remember what had changed and why, figure out what needed to be updated for this meeting, etc. The would generally take many many hours of faffing - with the templated config, it's now a few minutes.



## Quick start:

**Note**: This should generally be run from within the same directory where the templates are, as it makes tab-completion work.

See also 

This has been extended to use templates in the directory you are calling from (cwd), and
if not found, then a template in `<script_dir>/<platform>` where platform
defaults to JunOS. This allows one to have base templates and replace them with
sire specific ones. Currently very few are actually base...

```bash
$ ./build.py -r rtra all.j2
system {
    host-name RtrA;
    domain-name meeting.ietf.org;
    no-redirects;
    ...
```

## Variables

**NOTE: Everything which changes should be in a variable.**

Variables are all stored in YAML files. Here is an example:

```yaml
$ more vars/global.yaml
---
meeting: IETF104  # The meeting number - used for descriptions
domain: meeting.ietf.org
nameservers:
  - "31.130.229.6"
  - "31.130.229.7"
  - "2001:67c:370:229::6"
  - "2001:67c:370:229::7"
```

The build script checks that no two variables have the same name; it would be very confusing if domain-name was defined in one file, and then overridden in another. The way this works is that the script reads all the YAML configs, and errors on duplicates.

There **are** however some things which can repeat, with different values - an example of this is the hostname for devices; the hostname for RtrA will be different than that for RtrB. To allow this, we have *device specific* configs. If we are building a device specific config, we read in the `<device name>__device_specific.yaml` file. If you call the build script and specify a device (using the `--router=DEVICE` option), the script will include the config from this file.

## Templating

The [ Jinja2 template documentation](<http://jinja.pocoo.org/docs/2.10/templates/>) is good, but here is an (edited) example as a quick start:

```jinja2
system {
    host-name {{ hostname }};
    domain-name {{ domain }};
    name-server {
        {%- for nameserver in nameservers %}
        {{ nameserver }};
        {%- endfor %}
    }
}
```

Things in braces (`{{ }}`) are **variables**, and get replaced with the values when the template is rendered. In this example, the `{{ hostname }}` will be replaced with the value of the variable called `hostname`.

Often there are repeated parts of a config (e.g users). These are implemented using loops:

```jinja2
{%- for nameserver in nameservers %}
        {{ nameserver }};
        {%- endfor %}
```

This will loop over the array called nameservers, handing in a nameserver each time.

Often there are **optional** parts of a config, and we only want to include this if the variable is defined. Examples of this are things like BGP Multihop - here is an example:

```jinja2
{%- if peer.neighbor_multihop is defined %}
                multihop {
                   ttl {{peer.neighbor_multihop}};
                }
```

This will add the `multihop { ttl <number>}` bit if, and only if the variable `peer.neighbor_multihop` exists. Note that the way the script is currently configured (`undefined=StrictUndefined`), rendering the template will fail if you try and use an undefined variable.

**Note**: While it may be tempting to change this to allow undefined variables, this is a very bad idea - it will allow creating configs with bits missing, and silent failures.

### Including other templates

Having one huge template with all of the configlets in it would quickly become unmanageable, and so it is generally a good idea to split the config into multiple sections, and then have a master template which includes the others. Obviously you can nest this, so I generally have e.g. an `all.j2` template, which includes `protocols.j2`, which in turn includes `protocols-bgp.j2`,  `protocols-lldp.j2`,  `protocols-ospf.j2`, ... (the naming is simply convention, to help make it easier to remember where things fit, and so e.g `ls proto*` gives helpful results).

### Raising Errors

This program extends the Jinja2 syntax to allow raising an error and returning a  helpful error message from within the templating system. This is accomplished with the `raise <message>` syntax.

**Example:**

```jinja2
## chassis.j2
chassis {

    {%- if chassis is defined %}
        {%- if chassis == "mx240" %}{% include 'chassis-mx240.j2' %}
        {%- elif chassis == "mx204" %}{% include 'chassis-mx204.j2' %}
        {%- elif chassis == "ex4200" %}{% include 'chassis-ex4200.j2' %}
        {%- else %} {% raise "Only mx240, mx204, ex4200 chassis currently supported" %}
        {%- endif %}
    {%- else %}
        {% raise "chassis must be defined!" %}
    {%- endif %}
}
```



## Folder layout

A number of people have expressed confusion around the folder layout and template inheritance / overriding templates. To understand this, some background is helpful. 

This was originally written to generate configs for a single use (the IETF Meeting network). I then started using it to build configs for my own boxes, and then for some other projects, etc. I was doing this by having a single binary, and symlinking it into each project. I'd then copy all of the templates from the last project, and start futzing with them. This was annoying.

When I broke [router-config-builder](https://github.com/wkumari/router-config-builder) out into its own repo I wanted some way to make it easier for people to start using it, and also for me to make are projects, without having to copy the templates, track what is specific to each project, etc.

The design therefore now uses search paths to find each template. When referencing a template like `example.j2`, it will first search in the current directory, and if not found, it will then look in a platform specific directory (defaults to `junos`) in whatever directory the script lives. This means that you can add the [router-config-builder](https://github.com/wkumari/router-config-builder) submodule, and *override* any of the provided templates if needed. 

Here is an example (*at a repo which includes this repo as a submodule*):

```
.
├── commit-scripts
│   ├── int-addr-v4.slax
│   ├── int-addr-v6.slax
│   └── ospf-passive.slax
├── login.j2
├── protocols.j2
├── router-config-builder
│   ├── README.md
│   ├── build.py
│   └── junos
│       ├── all.j2
│       ├── chassis-ex4200.j2
│       ├── chassis-mx104.j2
│       ├── chassis-mx204.j2
│       ├── chassis-mx240.j2
│       ├── chassis.j2
│       ├── interfaces.j2
│       ├── protocols.j2
│       ├── system.j2
│       ├── system_services.j2
│       └── system_syslog.j2
├── system_services.j2
├── system_syslog.j2
└── vars
    ├── global.yaml
    ├── rtr1_device_specific.yaml
    └── rtr2_device_specific.yaml
```



In this example, I'm using the base `all, chassis, interfaces, system` templates, but I'm overriding and using my own (not in this git repo!) `login, system_services, system_syslog` templates, because they a: have confidential stuff (login), or are sufficiently odd that they should not exist in the base ones.

 

**More info:**

* **commit-scripts** This contains JunOS SLAX commit scripts. They do clever things like make firewall filters which match on interface IPs, automatically include interfaces in OSPF, etc. I'm considering adding them to the this repo.
* **login.j2** This contains the system login config stanza, including ssh keys, hashed passwords, etc. It doesn't go in this repo.
* **protocols.j2** I do (for the purpose of this example) some wild and crazy things with protocols. They are sufficiently odd that they are not based on the "base" templates, and should not be included in the "base" distribution. As a file called protocols.j2 exists in both this, and the `router-config-builder/junos` folder, this one will take precedence. 
* **router-config-builder** This is this repo. It is included in the parent repo (ie. `git submodule add git@github.com:wkumari/router-config-builder.git` )
* **router-config-builder/junos** These are the base (included) templates
* **router-config-builder/junos/protocols.j2**  This file is ignored, as there is a protocols.j2 in the "parent".
* **vars** This directory contains the YAML variables / parameters. `global.j2` applies to all devices, and `rtr1_device_specific.yaml` is only applied to a device called (invoked with `-r` rtr1.

While this may seem complex, it really isn't - perhaps the below will make it clearer:

```python
   script_dir = os.path.dirname(os.path.realpath(sys.argv[0]))

    env = Environment(loader = FileSystemLoader([path,
            os.path.join(script_dir, opts.platform)]),
        ...
        )
```



# Examples

Even though the variables / parameters files are mostly boring ("Oh! IPs in YAML, yawn.."), some examples are provided to help make the template examples more understandable.  These have been edited for brevity.

`global.yaml`

```yaml
---
meeting: IETF105  # The meeting number - used for descriptions
domain: meeting.ietf.org
as_number: 56554
engine_id: "[REDACTED]"
nameservers:
  - "31.130.229.6"
  - "2001:67c:370:229::6"
aggregates_v4:
  - "31.133.128.0/18"
  - "31.130.224.0/20"

# Note: Templates assume that we do the same things for OSPF and OSPF3
# Don't forget the unit number!
# This gets applied with an apply-macro
ospf:
    0:
      - interface: lo0
      - interface: et-0/0/0.0
        type: p2p
        metric: 1
      - interface: xe-0/0/0.0
        type: p2p
      - interface: ae0.300
        comment: "NAT64-Transit - high metric to inter router traffic stays on xe-0/0/2"
        metric: 1000
```



`external_interefaes.yaml`

```yaml
---
transits:
- desc: "Transit: Telus 1 (eth10 on scout)"
  interface: xe-0/1/3
  gigether_options:
    speed: 1g
  vlan: 1500
  mac: 02:1e:7f:00:00:01
  v4: 207.194.244.3/29
  v6: 2001:569:fff::14/127

- desc: "Transit: Telus 2 (eth11 on scout)"
  interface: xe-0/1/4
  gigether_options:
    speed: 1g
  mac: 02:1e:7f:00:00:02
  v4: 206.108.20.81/29
  v6: 2001:569:FFF:0:0:0:0:58/127

peers:
- desc: "Telus1"
  neighbor_v4: 207.194.244.1
  neighbor_v6: 2001:569:fff::15
  password: 1527178
  as: 852

```



 `rtra_device_specific.yaml`

```yaml
---
hostname: RtrA

addr_octet: 2  # This is combined with the subnet to make a full address.
               # It is used on VRRP interfaces.

# Device Specific Interfaces.
loopback_v4: 31.130.231.2
loopback_v6: 2001:67c:370:f231::2
```





### Templates

This is the "top level" template, and simply includes all of the others:

```jinja2 data-filename="test.py"
## all.j2
replace:
{% include 'groups.j2' %}
{% include 'system.j2' %}
{% include 'chassis.j2' %}
{% include 'services.j2' %}
{% include 'interfaces.j2' %}
{% include 'snmp.j2' %}
{% include 'forwarding_options.j2' %}
{% include 'routing_options.j2' %}
{% include 'protocols.j2' %}
{% include 'policy-options.j2' %}
{% include 'firewall.j2' %}
{% include 'applications.j2' %}
```



This defines the "system" configlet:

```jinja2
system {
    host-name {{ hostname }};
    domain-name {{ domain }};
    no-redirects;
    arp {
        passive-learning;
    }
    internet-options {
        path-mtu-discovery;
    }
    root-authentication {
    encrypted-password "$6$XW....pd/"; ## SECRET-DATA
    }
    name-server {
        {%- for nameserver in nameservers %}
        {{ nameserver }};
        {%- endfor %}
    }
    scripts {
        commit {
            file int-addr-v4.slax;
            file int-addr-v6.slax;
            file ospf-passive.slax;
        }
    }
    {% include 'login.j2' %}
    {% include 'system_services.j2' %}
}
```



A snippet of the interfaces template:

```jinja2
    {%- for link in transits %}
    {{link.interface}}  {
        description "Transit: {{ link.desc }}";
        {%- if link.vlan is defined %}
        vlan-tagging;
        {%- endif %} {# link.vlan #}
        {%- if link.mac is defined %}
        mac {{ link.mac }};
        {%- endif %}
        {%- if link.gigether_options is defined %}
            gigether-options {
                {%- if link.gigether_options.auto_negotiation is defined and link.gigether_options.auto_negotiation is sameas true %}
                auto-negotiation;
                {%- endif %}
                {%- if link.gigether_options.speed is defined %}
                speed {{ link.gigether_options.speed }};
                {%- endif %} {# link.speed #}
            }
        {%- endif %} {# gig_ether #}
        {%- if link.vlan is defined %}
        unit {{ link.vlan }} {
        {%- else %}
        unit 0 {
        {%- endif %} {# link.vlan #}
            {%- if link.vlan is defined %}
            vlan-id {{ link.vlan }};
            {%- endif %} {# link.vlan #}
            {%- if link.v4 is defined %}
            family inet {
                filter {
                    input-list [ DDoS_Protection Allow ];
                    output-list [ BCP38 Allow ];
                }
                address {{link.v4}};
            }
            {%- endif %}
            {%- if link.v6 is defined %}
            family inet6 {
                filter {
                    input Inbound-protect-v6;
                    output-list [ BCP38v6 ALLOW-v6 ];
                }
                address {{link.v6}};
            }
            {%- endif %}
        }
    }
   {%- endfor %}
```

