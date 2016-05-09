import unittest
from conans.model.options import OptionsValues, Options
from conans.model.ref import ConanFileReference
from conans.test.tools import TestBufferConanOutput


class OptionsTest(unittest.TestCase):

    def setUp(self):
        package_options = {"static": [True, False],
                           "optimized": [2, 3, 4]}
        values = "static=True\noptimized=3"
        self.sut = Options(package_options, values)

    def items_test(self):
        self.assertEqual(self.sut.items(), [("optimized", "3"), ("static", "True")])
        self.assertEqual(self.sut.items(), [("optimized", "3"), ("static", "True")])

    def boolean_test(self):
        self.sut.static = False
        self.assertFalse(self.sut.static)
        self.assertTrue(not self.sut.static)
        self.assertTrue(self.sut.static == False)
        self.assertFalse(self.sut.static == True)
        self.assertFalse(self.sut.static != False)
        self.assertTrue(self.sut.static != True)
        self.assertTrue(self.sut.static == "False")
        self.assertTrue(self.sut.static != "True")

    def basic_test(self):
        options = OptionsValues.loads("""other_option=True
        optimized_var=3
        Poco:deps_bundled=True
        Boost:static=False
        Boost:thread=True
        Boost:thread_multi=off
        Hello1:static=False
        Hello1:optimized=4
        """)
        down_ref = ConanFileReference.loads("Hello0/0.1@diego/testing")
        own_ref = ConanFileReference.loads("Hello1/0.1@diego/testing")
        output = TestBufferConanOutput()
        self.sut.propagate_upstream(options, down_ref, own_ref, output)
        self.assertEqual(self.sut.values.as_list(), [("optimized", "4"),
                                                     ("static", "False"),
                                                     ("Boost:static", "False"),
                                                     ("Boost:thread", "True"),
                                                     ("Boost:thread_multi", "off"),
                                                     ("Poco:deps_bundled", "True")])


        options2 = OptionsValues.loads("""other_option=True
        optimized_var=3
        Poco:deps_bundled=What
        Boost:static=2
        Boost:thread=Any
        Boost:thread_multi=on
        Hello1:static=True
        Hello1:optimized=2
        """)
        down_ref = ConanFileReference.loads("Hello2/0.1@diego/testing")
        self.sut.propagate_upstream(options2, down_ref, own_ref, output)
        self.assertIn("""WARN: Hello2/0.1@diego/testing tried to change Hello1/0.1@diego/testing option Hello1:optimized to 2
but it was already assigned to 4 by Hello0/0.1@diego/testing
WARN: Hello2/0.1@diego/testing tried to change Hello1/0.1@diego/testing option Hello1:static to True
but it was already assigned to False by Hello0/0.1@diego/testing
WARN: Hello2/0.1@diego/testing tried to change Hello1/0.1@diego/testing option Boost:static to 2
but it was already assigned to False by Hello0/0.1@diego/testing
WARN: Hello2/0.1@diego/testing tried to change Hello1/0.1@diego/testing option Boost:thread to Any
but it was already assigned to True by Hello0/0.1@diego/testing
WARN: Hello2/0.1@diego/testing tried to change Hello1/0.1@diego/testing option Boost:thread_multi to on
but it was already assigned to off by Hello0/0.1@diego/testing
WARN: Hello2/0.1@diego/testing tried to change Hello1/0.1@diego/testing option Poco:deps_bundled to What
but it was already assigned to True by Hello0/0.1@diego/testing""", str(output))
        self.assertEqual(self.sut.values.dumps(),
                         """optimized=4
static=False
Boost:static=False
Boost:thread=True
Boost:thread_multi=off
Poco:deps_bundled=True""")


class OptionsValuesTest(unittest.TestCase):

    def setUp(self):
        self.sut = OptionsValues.loads("""static=True
        optimized=3
        Poco:deps_bundled=True
        Boost:static=False
        Boost:thread=True
        Boost:thread_multi=off
        """)

    def test_from_list(self):
        option_values = OptionsValues(self.sut.as_list())
        self.assertEqual(option_values.dumps(), self.sut.dumps())

    def test_dumps(self):
        self.assertEqual(self.sut.dumps(), "\n".join(["optimized=3",
                                                     "static=True",
                                                     "Boost:static=False",
                                                     "Boost:thread=True",
                                                     "Boost:thread_multi=off",
                                                     "Poco:deps_bundled=True"]))

    def test_sha_constant(self):
        self.assertEqual(self.sut.sha, "2442d43f1d558621069a15ff5968535f818939b5")
        self.sut.new_option = False
        self.sut["Boost"].new_option = "off"
        self.sut["Poco"].new_option = 0
        #self.sut["Other"].new_option = 123
        self.assertEqual(self.sut.dumps(), "\n".join(["new_option=False",
                                                      "optimized=3",
                                                     "static=True",
                                                     "Boost:new_option=off",
                                                     "Boost:static=False",
                                                     "Boost:thread=True",
                                                     "Boost:thread_multi=off",
                                                     "Poco:deps_bundled=True",
                                                     "Poco:new_option=0"]))
        self.assertEqual(self.sut.sha, "2442d43f1d558621069a15ff5968535f818939b5")
