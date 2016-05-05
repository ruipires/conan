from conans.util.sha import sha1
from conans.errors import ConanException
import six

"""
SHA  ['optimized=3', 'static=True'] 8393e495c78151d27b26e5233e95a9e26b38e122
SHA  ['thread=True', 'thread.multi=off'] eca2fe206fa6b78c8d179650183e5e4f336c565b
SHA  ['deps_bundled=True'] dff9fb39569b7f795a3c4ea0759209fc4241a752
"""
class _ValuesProxy(object):
    def __init__(self, values, member):
        self._values = values
        self._member = member

    @property
    def _data(self):
        return self._values._data

    @property
    def _value(self):
        return self._data.get(self._member, "None")

    def __bool__(self):
        return self._value.lower() not in ["false", "none", "0", "off", ""]

    def __nonzero__(self):
        return self.__bool__()

    def __str__(self):
        return self._value

    def __repr__(self):
        return self._value

    def __eq__(self, other):
        return str(other) == self.__str__()

    def __ne__(self, other):
        return not self.__eq__(other)

    def __getattr__(self, attr):
        return _ValuesProxy(self, "%s.%s" % (self._member, attr))

    def __setattr__(self, attr, value):
        if attr[0] == "_":
            return super(_ValuesProxy, self).__setattr__(attr, value)
        setattr(self._values, "%s.%s" % (self._member, attr), value)


class Values(object):
    def __init__(self):
        self._data = {}
        self._modified = {}

    def serialize(self):
        return self.as_list()

    @staticmethod
    def deserialize(data):
        return Values.from_list(data)

    @property
    def fields(self):
        return sorted(self._data)

    def __getattr__(self, attr):
        if attr not in self._data:
            return None
        return _ValuesProxy(self, attr)

    def __setattr__(self, attr, value):
        if attr[0] == "_":
            return super(Values, self).__setattr__(attr, value)
        self._data[attr] = str(value)

    def copy(self):
        result = Values()
        result._data = self._data.copy()
        result._modified = self._modified.copy()
        return result

    @staticmethod
    def loads(text):
        result = Values()
        for line in text.splitlines():
            if not line.strip():
                continue
            name, value = line.split("=")
            result._data[name.strip()] = value.strip()
        return result

    @staticmethod
    def from_list(data):
        assert isinstance(data, list)
        result = Values()
        result._data = dict(data)
        return result

    def as_list(self):
        return sorted(self._data.items())

    def add(self, line):
        # FIXME: ugly interface, remove it
        name, value = line.split("=")
        self._data[name.strip()] = value.strip()

    def dumps(self):
        """ produces a text string with lines containine a flattened version:
        compiler.arch = XX
        compiler.arch.speed = YY
        """
        return "\n".join(["%s=%s" % (field, value)
                          for (field, value) in self.as_list()])

    @property
    def sha(self):
        result = []
        for (name, value) in self.as_list():
            # It is important to discard None values, so migrations in settings can be done
            # without breaking all existing packages SHAs, by adding a first "None" option
            # that doesn't change the final sha
            # FIXME: BUG HERE "." in name or value.lower() 
            if "." in name or value.lower() not in ["false", "none", "0", "off", ""]:
                result.append("%s=%s" % (name, value))
        return sha1('\n'.join(result).encode())

    def clear(self):
        self._data = {}

    def update_values(self, other):
        assert isinstance(other, Values)
        self._data.update(other._data)

    def propagate_upstream(self, other, down_ref, own_ref, output, package_name):
        if not other:
            return

        for (name, value) in sorted(other._data.items()):
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


class Values2(object):
    def __init__(self, value="values"):
        self._value = str(value)
        self._dict = {}  # {key: Values()}
        self._modified = {}  # {"compiler.version.arch": (old_value, old_reference)}

    def __getattr__(self, attr):
        if attr not in self._dict:
            return None
        return self._dict[attr]

    def clear(self):
        self._dict.clear()
        self._value = ""

    def __setattr__(self, attr, value):
        if attr[0] == "_":
            return super(Values, self).__setattr__(attr, value)
        self._dict[attr] = Values(value)

    def copy(self):
        """ deepcopy, recursive
        """
        cls = type(self)
        result = cls(self._value)
        for k, v in self._dict.items():
            result._dict[k] = v.copy()
        return result

    @property
    def fields(self):
        """ return a sorted list of fields: [compiler, os, ...]
        """
        return sorted(list(self._dict.keys()))

    def __bool__(self):
        return self._value.lower() not in ["false", "none", "0", "off", ""]

    def __nonzero__(self):
        return self.__bool__()

    def __str__(self):
        return self._value

    def __eq__(self, other):
        return str(other) == self.__str__()

    def __ne__(self, other):
        return not self.__eq__(other)

    @classmethod
    def loads(cls, text):
        result = []
        for line in text.splitlines():
            if not line.strip():
                continue
            name, value = line.split("=")
            result.append((name.strip(), value.strip()))
        return cls.from_list(result)

    def as_list(self, list_all=True):
        result = []
        for field in self.fields:
            value = getattr(self, field)
            if value or list_all:
                result.append((field, str(value)))
                child_lines = value.as_list()
                for (child_name, child_value) in child_lines:
                    result.append(("%s.%s" % (field, child_name), child_value))
        return result

    @classmethod
    def from_list(cls, data):
        result = cls()
        for (field, value) in data:
            tokens = field.split(".")
            attr = result
            for token in tokens[:-1]:
                attr = getattr(attr, token)
                if attr is None:
                    raise ConanException("%s not defined for %s\n"
                                         "Please define %s value first too"
                                         % (token, field, token))
            setattr(attr, tokens[-1], Values(value))
        return result

    def add(self, option_text):
        assert isinstance(option_text, six.string_types)
        name, value = option_text.split("=")
        tokens = name.strip().split(".")
        attr = self
        for token in tokens[:-1]:
            attr = getattr(attr, token)
        setattr(attr, tokens[-1], Values(value.strip()))

    def update(self, other):
        assert isinstance(other, Values)
        self._value = other._value
        for k, v in other._dict.items():
            if k in self._dict:
                self._dict[k].update(v)
            else:
                self._dict[k] = v.copy()

    def propagate_upstream(self, other, down_ref, own_ref, output, package_name):
        if not other:
            return

        current_values = {k: v for (k, v) in self.as_list()}
        for (name, value) in other.as_list():
            current_value = current_values.get(name)
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
                list_settings = name.split(".")
                attr = self
                for setting in list_settings[:-1]:
                    attr = getattr(attr, setting)
                setattr(attr, list_settings[-1], str(value))

    def dumps(self):
        """ produces a text string with lines containine a flattened version:
        compiler.arch = XX
        compiler.arch.speed = YY
        """
        return "\n".join(["%s=%s" % (field, value)
                          for (field, value) in self.as_list()])

    def serialize(self):
        return self.as_list()

    @classmethod
    def deserialize(cls, data):
        return cls.from_list(data)

    @property
    def sha(self):
        result = []
        for (name, value) in self.as_list(list_all=False):
            # It is important to discard None values, so migrations in settings can be done
            # without breaking all existing packages SHAs, by adding a first "None" option
            # that doesn't change the final sha
            if value != "None":
                result.append("%s=%s" % (name, value))
        print "SHA ", result, sha1('\n'.join(result).encode())
        return sha1('\n'.join(result).encode())
