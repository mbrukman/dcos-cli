import collections
import copy
import json
import os

import pkg_resources
import toml
from dcos import constants, jsonitem, subcommand, util
from dcos.errors import DCOSException

logger = util.get_logger(__name__)


def get_config_path():
    """ Returns the path to the DCOS config file.

    :returns: path to the DCOS config file
    :rtype: str
    """

    return os.environ.get(constants.DCOS_CONFIG_ENV, get_default_config_path())


def get_default_config_path():
    """Returns the default path to the DCOS config file.

    :returns: path to the DCOS config file
    :rtype: str
    """

    return os.path.expanduser(
        os.path.join("~",
                     constants.DCOS_DIR,
                     'dcos.toml'))


def get_config(mutable=False):
    """Returns the DCOS configuration object and creates config file is none
    found and `DCOS_CONFIG` set to default value

    :param mutable: True if the returned Toml object should be mutable
    :type mutable: boolean
    :returns: Configuration object
    :rtype: Toml | MutableToml
    """

    path = get_config_path()
    default = get_default_config_path()

    if path == default:
        util.ensure_dir_exists(os.path.dirname(default))
    return load_from_path(path, mutable)


def get_config_vals(keys, config=None):
    """Gets config values for each of the keys.  Raises a DCOSException if
    any of the keys don't exist.

    :param config: config
    :type config: Toml
    :param keys: keys in the config dict
    :type keys: [str]
    :returns: values for each of the keys
    :rtype: [object]
    """

    config = config or get_config()
    missing = [key for key in keys if key not in config]
    if missing:
        raise missing_config_exception(keys)

    return [config[key] for key in keys]


def missing_config_exception(keys):
    """ DCOSException for a missing config value

    :param keys: keys in the config dict
    :type keys: [str]
    :returns: DCOSException
    :rtype: DCOSException
    """

    msg = '\n'.join(
        'Missing required config parameter: "{0}".'.format(key) +
        '  Please run `dcos config set {0} <value>`.'.format(key)
        for key in keys)
    return DCOSException(msg)


def set_val(name, value):
    """
    :param name: name of paramater
    :type name: str
    :param value: value to set to paramater `name`
    :type param: str
    :returns: Toml config, message of change
    :rtype: Toml, str
    """

    toml_config = get_config(True)

    section, subkey = split_key(name)

    config_schema = get_config_schema(section)

    new_value = jsonitem.parse_json_value(subkey, value, config_schema)

    toml_config_pre = copy.deepcopy(toml_config)
    if section not in toml_config_pre._dictionary:
        toml_config_pre._dictionary[section] = {}

    value_exists = name in toml_config
    old_value = toml_config.get(name)

    toml_config[name] = new_value

    check_config(toml_config_pre, toml_config)

    save(toml_config)

    msg = "[{}]: ".format(name)
    if name == "core.dcos_acs_token":
        if not value_exists:
            msg += "set"
        elif old_value == new_value:
            msg += "already set to that value"
        else:
            msg += "changed"
    elif not value_exists:
        msg += "set to '{}'".format(new_value)
    elif old_value == new_value:
        msg += "already set to '{}'".format(old_value)
    else:
        msg += "changed from '{}' to '{}'".format(old_value, new_value)

    return toml_config, msg


def load_from_path(path, mutable=False):
    """Loads a TOML file from the path

    :param path: Path to the TOML file
    :type path: str
    :param mutable: True if the returned Toml object should be mutable
    :type mutable: boolean
    :returns: Map for the configuration file
    :rtype: Toml | MutableToml
    """

    util.ensure_file_exists(path)
    with util.open_file(path, 'r') as config_file:
        try:
            toml_obj = toml.loads(config_file.read())
        except Exception as e:
            raise DCOSException(
                'Error parsing config file at [{}]: {}'.format(path, e))
        return (MutableToml if mutable else Toml)(toml_obj)


def save(toml_config):
    """
    :param toml_config: TOML configuration object
    :type toml_config: MutableToml or Toml
    """

    serial = toml.dumps(toml_config._dictionary)
    path = get_config_path()
    with util.open_file(path, 'w') as config_file:
        config_file.write(serial)


def _get_path(toml_config, path):
    """
    :param config: Dict with the configuration values
    :type config: dict
    :param path: Path to the value. E.g. 'path.to.value'
    :type path: str
    :returns: Value stored at the given path
    :rtype: double, int, str, list or dict
    """

    for section in path.split('.'):
        toml_config = toml_config[section]

    return toml_config


def unset(name):
    """
    :param name: name of config value to unset
    :type name: str
    :returns: message of property removed
    :rtype: str
    """

    toml_config = get_config(True)
    toml_config_pre = copy.deepcopy(toml_config)
    section = name.split(".", 1)[0]
    if section not in toml_config_pre._dictionary:
        toml_config_pre._dictionary[section] = {}
    value = toml_config.pop(name, None)
    if value is None:
        raise DCOSException("Property {!r} doesn't exist".format(name))
    elif isinstance(value, collections.Mapping):
        raise DCOSException(_generate_choice_msg(name, value))
    else:
        save(toml_config)
        return "Removed [{}]".format(name)


def _generate_choice_msg(name, value):
    """
    :param name: name of the property
    :type name: str
    :param value: dictionary for the value
    :type value: dcos.config.Toml
    :returns: an error message for top level properties
    :rtype: str
    """

    message = ("Property {!r} doesn't fully specify a value - "
               "possible properties are:").format(name)
    for key, _ in sorted(value.property_items()):
        message += '\n{}.{}'.format(name, key)

    return message


def _iterator(parent, dictionary):
    """
    :param parent: Path to the value parameter
    :type parent: str
    :param dictionary: Value of the key
    :type dictionary: collection.Mapping
    :returns: An iterator of tuples for each property and value
    :rtype: iterator of (str, any) where any can be str, int, double, list
    """

    for key, value in dictionary.items():

        new_key = key
        if parent is not None:
            new_key = "{}.{}".format(parent, key)

        if not isinstance(value, collections.Mapping):
            yield (new_key, value)
        else:
            for x in _iterator(new_key, value):
                yield x


def split_key(name):
    """
    :param name: the full property path - e.g. marathon.url
    :type name: str
    :returns: the section and property name
    :rtype: (str, str)
    """

    terms = name.split('.', 1)
    if len(terms) != 2:
        raise DCOSException('Property name must have both a section and '
                            'key: <section>.<key> - E.g. marathon.url')

    return (terms[0], terms[1])


def get_config_schema(command):
    """
    :param command: the subcommand name
    :type command: str
    :returns: the subcommand's configuration schema
    :rtype: dict
    """

    # core.* config variables are special.  They're valid, but don't
    # correspond to any particular subcommand, so we must handle them
    # separately.
    if command == "core":
        return json.loads(
            pkg_resources.resource_string(
                'dcos',
                'data/config-schema/core.json').decode('utf-8'))

    executable = subcommand.command_executables(command)
    return subcommand.config_schema(executable, command)


def get_property_description(section, subkey):
    """
    :param section: section of config paramater
    :type section: str
    :param subkey: property within 'section'
    :type subkey: str
    :returns: description of section.subkey or None if no description
    :rtype: str | None
    """

    schema = get_config_schema(section)
    property_info = schema["properties"].get(subkey)
    if property_info is not None:
        return property_info.get("description")
    else:
        raise DCOSException(
            "No schema found found for {}.{}".format(section, subkey))


def check_config(toml_config_pre, toml_config_post):
    """
    :param toml_config_pre: dictionary for the value before change
    :type toml_config_pre: dcos.api.config.Toml
    :param toml_config_post: dictionary for the value with change
    :type toml_config_post: dcos.api.config.Toml
    :returns: process status
    :rtype: int
    """

    errors_pre = util.validate_json(toml_config_pre._dictionary,
                                    generate_root_schema(toml_config_pre))
    errors_post = util.validate_json(toml_config_post._dictionary,
                                     generate_root_schema(toml_config_post))

    logger.info('Comparing changes in the configuration...')
    logger.info('Errors before the config command: %r', errors_pre)
    logger.info('Errors after the config command: %r', errors_post)

    if len(errors_post) != 0:
        if len(errors_pre) == 0:
            raise DCOSException(util.list_to_err(errors_post))

        def _errs(errs):
            return set([e.split('\n')[0] for e in errs])

        diff_errors = _errs(errors_post) - _errs(errors_pre)
        if len(diff_errors) != 0:
            raise DCOSException(util.list_to_err(errors_post))


def generate_choice_msg(name, value):
    """
    :param name: name of the property
    :type name: str
    :param value: dictionary for the value
    :type value: dcos.config.Toml
    :returns: an error message for top level properties
    :rtype: str
    """

    message = ("Property {!r} doesn't fully specify a value - "
               "possible properties are:").format(name)
    for key, _ in sorted(value.property_items()):
        message += '\n{}.{}'.format(name, key)

    return message


def generate_root_schema(toml_config):
    """
    :param toml_configs: dictionary of values
    :type toml_config: TomlConfig
    :returns: configuration_schema
    :rtype: jsonschema
    """

    root_schema = {
        '$schema': 'http://json-schema.org/schema#',
        'type': 'object',
        'properties': {},
        'additionalProperties': False,
    }

    # Load the config schema from all the subsections into the root schema
    for section in toml_config.keys():
        config_schema = get_config_schema(section)
        root_schema['properties'][section] = config_schema

    return root_schema


class Toml(collections.Mapping):
    """Class for getting value from TOML.

    :param dictionary: configuration dictionary
    :type dictionary: dict
    """

    def __init__(self, dictionary):
        self._dictionary = dictionary

    def __getitem__(self, path):
        """
        :param path: Path to the value. E.g. 'path.to.value'
        :type path: str
        :returns: Value stored at the given path
        :rtype: double, int, str, list or dict
        """

        toml_config = _get_path(self._dictionary, path)
        if isinstance(toml_config, collections.Mapping):
            return Toml(toml_config)
        else:
            return toml_config

    def __iter__(self):
        """
        :returns: Dictionary iterator
        :rtype: iterator
        """

        return iter(self._dictionary)

    def property_items(self):
        """Iterator for full-path keys and values

        :returns: Iterator for pull-path keys and values
        :rtype: iterator of tuples
        """

        return _iterator(None, self._dictionary)

    def __len__(self):
        """
        :returns: The length of the dictionary
        :rtype: int
        """

        return len(self._dictionary)


class MutableToml(collections.MutableMapping):
    """Class for managing CLI configuration through TOML.

    :param dictionary: configuration dictionary
    :type dictionary: dict
    """

    def __init__(self, dictionary):
        self._dictionary = dictionary

    def __getitem__(self, path):
        """
        :param path: Path to the value. E.g. 'path.to.value'
        :type path: str
        :returns: Value stored at the given path
        :rtype: double, int, str, list or dict
        """

        toml_config = _get_path(self._dictionary, path)
        if isinstance(toml_config, collections.MutableMapping):
            return MutableToml(toml_config)
        else:
            return toml_config

    def __iter__(self):
        """
        :returns: Dictionary iterator
        :rtype: iterator
        """

        return iter(self._dictionary)

    def property_items(self):
        """Iterator for full-path keys and values

        :returns: Iterator for pull-path keys and values
        :rtype: iterator of tuples
        """

        return _iterator(None, self._dictionary)

    def __len__(self):
        """
        :returns: The length of the dictionary
        :rtype: int
        """

        return len(self._dictionary)

    def __setitem__(self, path, value):
        """
        :param path: Path to set
        :type path: str
        :param value: Value to store
        :type value: double, int, str, list or dict
        """

        toml_config = self._dictionary

        sections = path.split('.')
        for section in sections[:-1]:
            toml_config = toml_config.setdefault(section, {})

        toml_config[sections[-1]] = value

    def __delitem__(self, path):
        """
        :param path: Path to delete
        :type path: str
        """
        toml_config = self._dictionary

        sections = path.split('.')
        for section in sections[:-1]:
            toml_config = toml_config[section]

        del toml_config[sections[-1]]
