import unittest
from conans.model.options import OptionsValues, Options, Values
from conans.model.ref import ConanFileReference
from conans.test.tools import TestBufferConanOutput
from conans.errors import ConanException


class OptionsTest(unittest.TestCase):

    def values_test(self):
        values = Values([("c", "off"), ("a", 2), ("b", 4)])
        self.assertEqual(values.a, 2)
        self.assertTrue(values.b)
        self.assertFalse(values.c)
        self.assertNotEqual(values.b, 3)
        self.assertEqual(values.c.value, "off")

        # modify some values
        values.a = 8
        self.assertEqual(values.a, "8")
        values.c = "On"
        self.assertTrue(values.c)

        # item access
        self.assertEqual(values["a"], 8)
        self.assertEqual(values["a"], "8")
        values["a"] = 5
        self.assertEqual(values["a"], 5)
        self.assertEqual(values["a"], "5")

        self.assertEqual(values.fields, ["a", "b", "c"])

    def values_propagate_test(self):
        values = Values([("c", "off"), ("a", 2), ("b", 4)])
        down_values = Values([("a", 5), ("d", 123)])
        output = TestBufferConanOutput()
        values.propagate_upstream(down_values, "Down", "Me", output, "Name")
        self.assertEqual(values.fields, ["a", "b", "c", "d"])
        self.assertEqual(values.a, 5)
        self.assertEqual(values.d, "123")
        self.assertEqual(output, "")

        # Try again, get warning
        other_down_values = Values([("a", 18), ("d", 23)])
        values.propagate_upstream(other_down_values, "OtherDown", "Me", output, "Name")
        # Values not changed
        self.assertEqual(values.a, 5)
        self.assertEqual(values.d, "123")

        # Warnings
        self.assertIn("""WARN: OtherDown tried to change Me option Name:a to 18
but it was already assigned to 5 by Down
WARN: OtherDown tried to change Me option Name:d to 23
but it was already assigned to 123 by Down""", output)

        self.assertEqual(values.sha, "ea9e24d2c0a2288823889899b00b65b5e1a482b5")

    def options_values_test(self):
        values1 = OptionsValues([("c", "off"), ("a", 2), ("Pack:b", 4)])
        values2 = OptionsValues.loads("c=off\na=2\nPack:b=4")

        for values in (values1, values2):
            self.assertEqual(values.a, 2)
            self.assertEqual(values.a, "2")
            self.assertTrue(values.a)
            self.assertFalse(values.c)

            # setattr
            values.c = 13
            self.assertEqual(values.c, "13")

            # getitem + get/set attr
            self.assertEqual(values["Pack"].b, 4)
            self.assertEqual(values["Pack"].b, "4")
            values["Pack"].b = 81
            self.assertEqual(values["Pack"].b, 81)
            self.assertEqual(values["Pack"].b, "81")

            # setitem
            values["Other"] = [("j", 123)]
            self.assertEqual(values["Other"].j, "123")

    def options_test(self):
        options = Options({"option1": [1, 2], "option2": [3, 4], "option3": []})
        # Normal assignment
        options.option1 = 1
        options.option2 = 4
        options.option3 = "PI"
        self.assertEqual(options.option1, 1)
        self.assertEqual(options.option2, 4)
        self.assertEqual(options.option3, "PI")

        # Failed assignment
        with self.assertRaisesRegexp(ConanException, "Possible values are"):
            options.option1 = 3

        # Failed comparison
        with self.assertRaisesRegexp(ConanException, "Possible values are"):
            assert options.option1 == 4

        # Others Assignment
        options["Other"].j = 3
        self.assertEqual(options["Other"].j, "3")

    def options_validate_test(self):
        options = Options({"option1": [1, 2], "option2": [3, 4], "option3": []})
        with self.assertRaisesRegexp(ConanException, "not defined"):
            options.validate()

        options.option1 = 1
        options.option2 = 3
        options.option3 = None
        options.validate()

    def options_initialize_test(self):
        options = Options({"option1": [1, 2], "option2": [3, 4], "option3": []})
        # Normal assignment
        options.option1 = 1
        options.option2 = 4
        options.option3 = "PI"

        values = OptionsValues.loads("Pack:option4=3\noption1=2")
        options.initialize_upstream(values)
        self.assertEqual(options["Pack"].option4, 3)
        self.assertEqual(options.option1, 2)
        self.assertEqual(options.option2, 4)
        self.assertEqual(options.option3, "PI")

    def options_propagate_test(self):
        options = Options({"option1": [1, 2], "option2": [3, 4], "option3": []})
        # Normal assignment
        options.option1 = 1
        options.option2 = 4
        options.option3 = "PI"

        values = OptionsValues.loads("Pack:option4=3\nOwnRef:option1=2")
        output = TestBufferConanOutput()
        own_ref = ConanFileReference.loads("OwnRef/0.1@user/channel")
        options.propagate_upstream(values, "DOWN", own_ref, output)

        self.assertEqual(options["Pack"].option4, 3)
        self.assertEqual(options.option1, 2)
        self.assertEqual(options.option2, 4)
        self.assertEqual(options.option3, "PI")
