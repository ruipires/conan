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
        assert isinstance(value, str)
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
        if data:  # list
            data = [(str(k), str(v)) for (k, v) in data]
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

    def remove(self, field):
        self._data.pop(field, None)
        self._modified.pop(field, None)

    def clear(self):
        self._data.clear()
        self._modified.clear()

    @property
    def fields(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    iteritems = items
    as_list = items

    def update(self, other):
        assert isinstance(other, Values)
        self._data.update(other._data)

    def propagate_upstream(self, other, down_ref, own_ref, output, package_name):
        if not other:
            return

        assert isinstance(other, Values), type(other)
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

    def __repr__(self):
        return self.dumps()


def bad_value_msg(value, value_range):
    return ("'%s' is not a valid 'option' value.\nPossible values are %s" % (value, value_range))


def undefined_field(field, fields=None):
    result = ["'%s' doesn't exist" % (field)]
    result.append(" possible configurations are %s" % (fields or "none"))
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
        self.__dict__["_data"] = {str(k): [str(v) for v in vals] for k, vals in definition.items()}
        assert isinstance(values, Values)
        self.__dict__["_values"] = values

    def validate(self):
        # FIXME: implement
        return True

    @property
    def fields(self):
        return sorted(list(self._data.keys()))

    def remove(self, item):
        if not isinstance(item, (list, tuple, set)):
            item = [item]
        for it in item:
            it = str(it)
            self._data.pop(it, None)
            self._values.remove(it)

    def clear(self):
        self._data = {}
        self._values.clear()

    def _ranges(self, field):
        try:
            return self._data[field]
        except KeyError:
            raise ConanException(undefined_field(field, self.fields))

    def __getattr__(self, field):
        ranges = self._ranges(field)
        value = self._values[field]
        return OptionItem(value.value, ranges)

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

    def propagate_upstream(self, values, down_ref, own_ref, output, name):
        assert isinstance(values, Values)
        for k, v in values.items():
            ranges = self._ranges(k)
            if ranges and v not in ranges:
                raise ConanException(bad_value_msg(v, ranges))
        self._values.propagate_upstream(values, down_ref, own_ref, output, name)
        # Implement check

    def update(self, values):
        assert isinstance(values, Values)
        for k, v in values.items():
            ranges = self._ranges(k)
            if ranges and v not in ranges:
                raise ConanException(bad_value_msg(v, ranges))
        print "PackageOptionsValues PRE update ", self._values
        print "With values ", values
        self._values.update(values)
        print "PackageOptionsValues POST update ", self._values


class Options(object):
    """ all options of a package, both its own options and the upstream
    ones.
    Owned by conanfile
    """
    def __init__(self, options, values):
        values = values or []
        options = options or {}
        if isinstance(values, tuple):
            package_values = OptionsValues.loads("\n".join(values))
        elif isinstance(values, list):
            package_values = OptionsValues(values)
        elif isinstance(values, str):
            package_values = OptionsValues.loads(values)
        else:
            raise ConanException("Please define your default_options as list or "
                                 "multiline string")

        # Addressed only by name, as only 1 configuration is allowed
        # if more than 1 is present, 1 should be "private" requirement and its options
        # are not public, not overridable
        print "Options: Package values ", package_values
        self.__dict__["_values"] = package_values
        self.__dict__["_package_options"] = PackageOptions(options, self._values._package_values)

    def clear(self):
        self._package_options.clear()

    def __getitem__(self, item):
        print "OPtions:Getitem ", item
        return self._values[item]

    def __getattr__(self, attr):
        print "OPtions:gettar ", attr
        return getattr(self._package_options, attr)

    def __setattr__(self, attr, value):
        print "Options: settattr ", attr, value
        return setattr(self._package_options, attr, value)

    @property
    def values(self):
        print "Options: Returngin Package values ", self._values
        return self._values

    @values.setter
    def values(self, v):
        raise NotImplementedError("WHO IS SETTING ME?")

    def propagate_upstream(self, values, down_ref, own_ref, output):
        """ used to propagate from downstream the options to the upper requirements
        """
        if values is not None:
            assert isinstance(values, OptionsValues)
            own_values = values._values.get(own_ref.name)
            if own_values:
                self._package_options.propagate_upstream(own_values, down_ref, own_ref, output,
                                                         own_ref.name)
            for name, option_values in values._values.items():
                if name != own_ref.name:
                    self._values[name].propagate_upstream(option_values, down_ref, own_ref, output,
                                                          name)

    def initialize_upstream(self, values):
        """ used to propagate from downstream the options to the upper requirements
        """
        print "Options: initialize_upstream PRE ", self._values
        if values is not None:
            assert isinstance(values, OptionsValues)
            self._package_options.update(values._package_values)
            for name, option_values in values._values.items():
                self._values.update(name, option_values)
        print "Options: initialize_upstream POST ", self._values

    def validate(self):
        return self._package_options.validate()

    def propagate_downstream(self, ref, options):
        assert isinstance(options, OptionsValues)
        print "Options: Propagating downstream PRE ", self._values
        self._values[ref.name] = options._package_values
        for k, v in options._values.items():
            self._values[k] = v
        print "Options: Propagating downstream POST ", self._values

    def clear_unused(self, references):
        """ remove all options not related to the passed references,
        that should be the upstream requirements
        """
        print "Options: Clear unused PRE ", self._values
        existing_names = [r.conan.name for r in references]
        for name in self._values._values.keys():
            if name not in existing_names:
                self._values.pop(name)
        print "Options: Clear unused POST ", self._values


class OptionsValues(object):
    """ static= True,
    Boost.static = False,
    Poco.optimized = True
    """
    def __init__(self, values=None):
        values = values or []
        assert isinstance(values, list)
        values_dict = defaultdict(list)
        values_dict[None] = []
        for (k, v) in values:
            tokens = k.split(":")
            if len(tokens) == 2:
                package, option = tokens
            else:
                package = None
                option = k
            values_dict[package].append((option, str(v)))
        package_options = values_dict.pop(None)
        values = {k: Values(v) for k, v in values_dict.items()}
        self.__dict__["_package_values"] = Values(package_options)
        self.__dict__["_values"] = SortedDict(values)  # {name("Boost": Values}

    @staticmethod
    def loads(text):
        value_list = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            name, value = line.split("=")
            value_list.append((name.strip(), value.strip()))
        return OptionsValues(value_list)

    def __getitem__(self, item):
        return self._values.setdefault(item, Values())

    def __setitem__(self, item, values):
        assert isinstance(values, Values)
        self._values[item] = values

    def pop(self, item):
        return self._values.pop(item, None)

    def __repr__(self):
        return self.dumps()

    def __getattr__(self, attr):
        return getattr(self._package_values, attr)

    def __setattr__(self, attr, value):
        print "OptionsValues: settattr ", attr, value
        return setattr(self._package_values, attr, value)

    def clear_indirect(self):
        for v in self._values.values():
            v.clear()

    def as_list(self):
        result = []
        options_list = self._package_values.as_list()
        if options_list:
            result.extend(options_list)
        for k, v in self._values.items():
            for line in v.as_list():
                line_key, line_value = line
                result.append(("%s:%s" % (k, line_key), line_value))
        return result

    def dumps(self):
        result = []
        for key, value in self.as_list():
            result.append("%s=%s" % (key, value))
        return "\n".join(result)

    @property
    def sha(self):
        result = []
        print "self sha ", self._package_values.sha
        result.append(self._package_values.sha)
        for name, value in self.as_list():
            print "Value sha ", name, "= ", value.sha
            result.append(value.sha)
        return sha1('\n'.join(result).encode())

    def serialize(self):
        ret = {}
        ret["options"] = self._package_values.serialize()
        ret["req_options"] = {}
        for name, values in self._values.items():
            ret["req_options"][name] = values.serialize()
        return ret

    @staticmethod
    def deserialize(data):
        values = {k: Values(v) for k, v in data["req_options"].items()}
        return OptionsValues(data["options"], values)

    def update(self, name, values):
        raise Exception("BOOM2")
