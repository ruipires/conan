from conans.util.sha import sha1
from collections import defaultdict
from conans.errors import ConanException
import yaml
import six
from sortedcontainers.sorteddict import SortedDict


class OptionItem(object):
    """ This is now just a view over a single item
    """
    def __init__(self, value, range_values=None):
        self._value = value
        self._range = range_values

    def __bool__(self):
        if not self._value:
            return False
        return self._value.lower() not in ["false", "none", "0", "off", ""]

    def __nonzero__(self):
        return self.__bool__()

    def __str__(self):
        return self._value

    def __eq__(self, other):
        if other is None:
            return self._value is None
        other = str(other)
        if self._range and other not in self._range:
            raise ConanException(bad_value_msg(other, self._range))
        return other == self._value

    def __ne__(self, other):
        return not self.__eq__(other)

    @property
    def value(self):
        return self._value


class Values(object):
    def __init__(self, data=None):
        self.__dict__["_data"] = SortedDict(data)
        self.__dict__["_modified"] = {}  # {"compiler.version.arch": (old_value, old_reference)}

    def __getattr__(self, attr):
        try:
            return OptionItem(self._data[attr])
        except KeyError:
            return None

    def __setattr__(self, attr, value):
        self._data[attr] = str(value)

    __getitem__ = __getattr__
    __setitem__ = __setattr__

    @property
    def fields(self):
        return self._data.keys()

    @staticmethod
    def loads(text):
        result = []
        for line in text.splitlines():
            if not line.strip():
                continue
            name, value = line.split("=")
            result.append((name.strip(), value.strip()))
        return Values(result)

    def items(self):
        return self._data.items()

    iteritems = items
    as_list = items

    def add(self, option_text):
        assert isinstance(option_text, six.string_types)
        name, value = option_text.split("=")
        self._data[name] = value

    def update(self, other):
        assert isinstance(other, Values)
        self._data.update(other._data)

    def propagate_upstream(self, other, down_ref, own_ref, output, package_name):
        if not other:
            return

        for (name, value) in other._data.items():
            current_value = self._data.get(name)
            if value == current_value:
                continue

            modified = self._modified.get(name)
            if modified is not None:
                modified_value, modified_ref = modified
                if modified_value == value:
                    continue
                else:
                    output.warn("%s tried to change %s option %s:%s to %s\n"
                                "but it was already assigned to %s by %s"
                                % (down_ref, own_ref, package_name, name, value,
                                   modified_value, modified_ref))
            else:
                self._modified[name] = (value, down_ref)
                self._data[name] = value

    def dumps(self):
        """ produces a text string with lines containine a flattened version:
        compiler.arch = XX
        compiler.arch.speed = YY
        """
        return "\n".join(["%s=%s" % (field, value)
                          for (field, value) in self._data.items()])

    def serialize(self):
        return self._data.items()

    @staticmethod
    def deserialize(data):
        return Values(data)

    @property
    def sha(self):
        result = []
        for (name, value) in self._data.items():
            # It is important to discard None values, so migrations in settings can be done
            # without breaking all existing packages SHAs, by adding a first "None" option
            # that doesn't change the final sha
            if value and value.lower() not in ["false", "none", "0", "off"]:
                result.append("%s=%s" % (name, value))
        return sha1('\n'.join(result).encode())


def bad_value_msg(value, value_range):
    return ("'%s' is not a valid 'option' value.\nPossible values are %s" % (value, value_range))


def undefined_field(field, fields=None):
    result = ["'%s' doesn't exist" % (field)]
    result.append("'%s' possible configurations are %s" % (fields or "none"))
    return "\n".join(result)


def undefined_value(name):
    return "'%s' value not defined" % name


class ConfigItem(OptionItem):
    """ This is now just a view over the single level COnfigDict
    """
    def remove(self, values):
        if not self._range:
            return
        if not isinstance(values, (list, tuple, set)):
            values = [values]
        for v in values:
            v = str(v)
            if self._value == v:
                raise ConanException(bad_value_msg(v, self._range))
            try:
                self._range.remove(v)
            except ValueError:
                pass  # not in list


class PackageOptions(object):
    def __init__(self, definition, values):
        self._data = {str(k): [str(v) for v in vals] for k, vals in definition.items()}
        self._values = Values(values)

    @property
    def fields(self):
        return sorted(list(self._data.keys()))

    def remove(self, item):
        if not isinstance(item, (list, tuple, set)):
            item = [item]
        for it in item:
            it = str(it)
            self._data.pop(it, None)

    def clear(self):
        self._data = {}
        self._values = Values()

    def _ranges(self, field):
        try:
            return self._data[field]
        except KeyError:
            raise ConanException(undefined_field(field, self.fields))

    def __getattr__(self, field):
        ranges = self._ranges(field)
        value = self._values[field]
        return OptionItem(value, ranges)

    def __setattr__(self, field, value):
        ranges = self._ranges(field)
        value = str(value)
        if ranges and value not in ranges:
            raise ConanException(bad_value_msg(value, ranges))
        self._values[field] = value

    @property
    def values(self):
        return self._values

    def items(self):
        return self._values.items()

    def iteritems(self):
        return self._values.iteritems()

    def propagate_upstream(self, values, down_ref, own_ref, output):
        """ update must be controlled, to not override lower
        projects options
        """
        if not values:
            return

        current_values = {k: v for (k, v) in self.values_list}
        for (name, value) in values.as_list():
            current_value = current_values.get(name)
            if value == current_value:
                continue

            modified = self._modified.get(name)
            if modified is not None:
                modified_value, modified_ref = modified
                if modified_value == value:
                    continue
                else:
                    output.warn("%s tried to change %s option %s to %s\n"
                                "but it was already assigned to %s by %s"
                                % (down_ref, own_ref, name, value, modified_value, modified_ref))
            else:
                self._modified[name] = (value, down_ref)
                list_settings = name.split(".")
                attr = self
                for setting in list_settings[:-1]:
                    attr = getattr(attr, setting)
                setattr(attr, list_settings[-1], str(value))


class Options(object):
    """ all options of a package, both its own options and the upstream
    ones.
    Owned by conanfile
    """
    def __init__(self, options, values):
        assert isinstance(options, PackageOptions)
        self._options = options
        # Addressed only by name, as only 1 configuration is allowed
        # if more than 1 is present, 1 should be "private" requirement and its options
        # are not public, not overridable
        self._reqs_options = {}  # {name("Boost": Values}

    def clear(self):
        self._options.clear()

    def __getitem__(self, item):
        return self._reqs_options.setdefault(item, Values())

    def __getattr__(self, attr):
        return getattr(self._options, attr)

    def __setattr__(self, attr, value):
        if attr[0] == "_" or attr == "values":
            return super(Options, self).__setattr__(attr, value)
        return setattr(self._options, attr, value)

    @property
    def values(self):
        result = OptionsValues()
        result._options = Values.from_list(self._options.values_list)
        for k, v in self._reqs_options.items():
            result._reqs_options[k] = v.copy()
        return result

    @values.setter
    def values(self, v):
        assert isinstance(v, OptionsValues)
        self._options.values = v._options
        self._reqs_options.clear()
        for k, v in v._reqs_options.items():
            self._reqs_options[k] = v.copy()

    def propagate_upstream(self, values, down_ref, own_ref, output):
        """ used to propagate from downstream the options to the upper requirements
        """
        if values is not None:
            assert isinstance(values, OptionsValues)
            own_values = values.pop(own_ref.name)
            self._options.propagate_upstream(own_values, down_ref, own_ref, output)
            for name, option_values in sorted(list(values._reqs_options.items())):
                self._reqs_options.setdefault(name, Values()).propagate_upstream(option_values,
                                                                                 down_ref,
                                                                                 own_ref,
                                                                                 output,
                                                                                 name)

    def initialize_upstream(self, values):
        """ used to propagate from downstream the options to the upper requirements
        """
        if values is not None:
            assert isinstance(values, OptionsValues)
            self._options.values = values._options
            for name, option_values in values._reqs_options.items():
                self._reqs_options.setdefault(name, Values()).update(option_values)

    def validate(self):
        return self._options.validate()

    def propagate_downstream(self, ref, options):
        assert isinstance(options, OptionsValues)
        self._reqs_options[ref.name] = options._options
        for k, v in options._reqs_options.items():
            self._reqs_options[k] = v.copy()

    def clear_unused(self, references):
        """ remove all options not related to the passed references,
        that should be the upstream requirements
        """
        existing_names = [r.conan.name for r in references]
        for name in list(self._reqs_options.keys()):
            if name not in existing_names:
                self._reqs_options.pop(name)


class OptionsValues(object):
    """ static= True,
    Boost.static = False,
    Poco.optimized = True
    """
    def __init__(self):
        self._options = Values()
        self._reqs_options = {}  # {name("Boost": Values}

    def __getitem__(self, item):
        return self._reqs_options.setdefault(item, Values())

    def pop(self, item):
        return self._reqs_options.pop(item, None)

    def __repr__(self):
        return self.dumps()

    def __getattr__(self, attr):
        return getattr(self._options, attr)

    def copy(self):
        result = OptionsValues()
        result._options = self._options.copy()
        for k, v in self._reqs_options.items():
            result._reqs_options[k] = v.copy()
        return result

    def __setattr__(self, attr, value):
        if attr[0] == "_":
            return super(OptionsValues, self).__setattr__(attr, value)
        return setattr(self._options, attr, value)

    def clear_indirect(self):
        for v in self._reqs_options.values():
            v.clear()

    def as_list(self):
        result = []
        options_list = self._options.as_list()
        if options_list:
            result.extend(options_list)
        for key in sorted(self._reqs_options.keys()):
            for line in self._reqs_options[key].as_list():
                line_key, line_value = line
                result.append(("%s:%s" % (key, line_key), line_value))
        return result

    @staticmethod
    def from_list(data):
        result = OptionsValues()
        by_package = defaultdict(list)
        for k, v in data:
            tokens = k.split(":")
            if len(tokens) == 2:
                package, option = tokens
                by_package[package.strip()].append((option, v))
            else:
                by_package[None].append((k, v))
        result._options = Values.from_list(by_package[None])
        for k, v in by_package.items():
            if k is not None:
                result._reqs_options[k] = Values.from_list(v)
        return result

    def dumps(self):
        result = []
        for key, value in self.as_list():
            result.append("%s=%s" % (key, value))
        return "\n".join(result)

    @staticmethod
    def loads(text):
        result = OptionsValues()
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            tokens = line.split(":")
            if len(tokens) == 2:
                package, option = tokens
                current = result._reqs_options.setdefault(package.strip(), Values())
            else:
                option = tokens[0].strip()
                current = result._options
            current.add(option)
        return result

    @property
    def sha(self):
        result = []
        result.append(self._options.sha)
        for key in sorted(list(self._reqs_options.keys())):
            result.append(self._reqs_options[key].sha)
        return sha1('\n'.join(result).encode())

    def serialize(self):
        ret = {}
        ret["options"] = self._options.serialize()
        ret["req_options"] = {}
        for name, values in self._reqs_options.items():
            ret["req_options"][name] = values.serialize()
        return ret

    @staticmethod
    def deserialize(data):
        result = OptionsValues()
        result._options = Values.deserialize(data["options"])
        for name, data_values in data["req_options"].items():
            result._reqs_options[name] = Values.deserialize(data_values)
        return result

