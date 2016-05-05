from conans.model.config_dict import ConfigDict
from conans.model.values import Values
from conans.util.sha import sha1
from collections import defaultdict


class PackageOptions(ConfigDict):
    """ Optional configuration of a package. Follows the same syntax as
    settings and all values will be converted to strings
    """
    def __init__(self, definition=None, name="options", parent_value=None):
        super(PackageOptions, self).__init__(definition or {}, name, parent_value)
        self._modified = {}  # {"compiler.version.arch": (old_value, old_reference)}

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
    def __init__(self, options):
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
                self._reqs_options.setdefault(name, Values()).update_values(option_values)

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

