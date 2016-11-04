from conans.model.ref import ConanFileReference
from conans.errors import ConanException


class RequireResolver(object):

    def __init__(self, output, local_search, remote_search):
        self._output = output
        self._local_search = local_search
        self._remote_search = remote_search

    def resolve(self, require):
        version_range = require.version_range()
        if not version_range:
            return
        ref = require.conan_reference
        search_ref = ConanFileReference(ref.name, "*", ref.user, ref.channel)
        search_ref = str(search_ref)
        resolved = self._resolve_local(search_ref, version_range)
        if not resolved:
            remote_found = self._remote_search.search_remotes(search_ref)
            if remote_found:
                resolved = self._resolve_version(version_range, remote_found)

        if resolved:
            require.conan_reference = resolved
        else:
            raise ConanException("The version in '%s' could not be resolved" % require)

    def _resolve_local(self, search_ref, version_range):
        if self._local_search:
            local_found = self._local_search.search(search_ref)
            if local_found:
                resolved_version = self._resolve_version(version_range, local_found)
                if resolved_version:
                    return resolved_version

    def _resolve_version(self, version_range, local_found):
        # FIXME: now always getting the latest one
        return local_found[-1]
