from unittest import TestCase

from netcode_parser import DONetcodeParser, Log

SHIFT_OP = "shiftOperationFromClientToServer"


class Test(TestCase):

    def assert_correct_shift(self, obj, shift_amt, shift_dir):
        self.assertEqual(obj["amount"], shift_amt)
        self.assertEqual(obj["direction"], shift_dir)
        pass

    def test_parse_field_definition_shifted(self):
        cases_fd = open("test_cases_expressions_shifted.csv", "r", encoding="UTF-8")
        cases = cases_fd.readlines()
        cases_fd.close()
        for case in cases:
            if case.strip() == "":
                continue
            Log.log_debug("-")
            code, data_type, amount, direction = case.strip().split(":")
            res = DONetcodeParser.parse_field_definition_shifted(code, data_type)

            self.assert_correct_shift(res[SHIFT_OP], int(amount), direction)
