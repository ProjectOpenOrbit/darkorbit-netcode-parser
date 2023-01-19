import re
from typing import IO

from netcode_parser.Log import *


# read all lines into a list and trim newlines
def read_body(handle: IO) -> list:
    return [line.replace("\r", "").replace("\n", "") for line in handle.readlines()]


def find_class_def_line(body) -> str:
    for line in body:
        if str(line).find("public class") != -1:
            return line.strip()


def parse_class_name(class_def_line: str) -> str:
    result = re.findall(r"(?<=public class )\w+", class_def_line)
    if len(result) < 1:
        raise RuntimeError(f"could not find class name in line '{class_def_line}'")
    class_name = result[0]
    return class_name


def parse_class_base(class_def_line: str) -> str:
    result = re.findall(r"(implements|extends) (\w+)", class_def_line)
    if len(result) < 1:
        raise RuntimeError(f"could not find base class name in line '{class_def_line}'")
    base_type = result[0][0]
    base_class = result[0][1]

    return base_class


def parse_class_definition(body) -> list:
    class_def_line = find_class_def_line(body)

    class_name = parse_class_name(class_def_line)
    class_base = parse_class_base(class_def_line)

    # print(f"Class {class_name} -> {class_base}")
    return [class_name, class_base]


def parse_constants(body) -> list:
    constants = []
    for line in body:
        if line.find("const const") != -1:
            res = re.findall(r" const (\w+):(\w+) = (\w+)", line)
            if len(res) < 1:
                raise RuntimeError(f"could not parse const definition in line {line}")
            # print(f"\t{res}")
            if res[0][1] != 'int':
                raise RuntimeError(f"unknown base type {res[0][1]} in line {line}")
            constant = {"name": res[0][0], "type": res[0][1], "value": res[0][2]}
            constants.append(constant)
    return constants


def should_skip_class(body: list) -> bool:
    for line in body:
        if line.find("Not decompiled") != -1:
            return True
        if line.find("createInstance(param1:int) : IModule") != -1:
            # This is the ModuleFactory class. It contains no packet info we can parse.
            return True
    return False


def find_field_type_from_write_call_for_field_name(body: list, field_name: str) -> str:
    for inner_line in body:
        regex_type_result = re.findall(rf"param1.write(\w+).*{field_name}", inner_line)
        if len(regex_type_result) > 0:
            return regex_type_result[0]
    raise RuntimeError("could not find write call")


def parse_fields(body: list) -> list:
    fields = []
    for line in body:
        res = re.findall(r"public var (\w+):([\w<>.]+)", line)
        if len(res) < 1:
            continue
            # raise RuntimeError(f"could not parse field definition in line {line}")
        field = {"name": res[0][0], "initialName": res[0][0], "type": res[0][1]}
        if field["type"] == "int":
            # search field definition in write line, it could be a short instead
            field["type"] = find_field_type_from_write_call_for_field_name(body, field["name"])

        field["type"] = field.get("type").lower()
        log_debug(f"{field['type']} {field['name']};")
        fields.append(field)
    return fields


def parse_constructor_definition(body, module_name):
    for line in body:
        if line.find(f"function {module_name}") != -1:
            res = re.findall(r"(param\d+):([\w.<>]+)", line)
            constructor_definition = []
            for match in res:
                param_name = match[0]
                param_type = match[1]
                field_ref = ""
                # parse field reference
                for inner_line in body:
                    fld_ref_match = re.findall(rf"this\.(\w+) = {param_name}", inner_line)
                    if len(fld_ref_match) > 0:
                        field_ref = fld_ref_match[0]
                        break
                    else:
                        fld_ref_match = re.findall(r"super\(([\w.<>,]+)\)", inner_line)
                        if len(fld_ref_match) < 1:
                            continue
                        super_params: str = fld_ref_match[0]
                        params_split = super_params.split(",")
                        if param_name in params_split:
                            idx = params_split.index(param_name)
                            field_ref = f"super${idx}"
                            break

                if field_ref == "":
                    raise RuntimeError("Could not find field ref")
                constructor_definition.append({"type": param_type, "name": param_name, "fieldRef": field_ref})
            return constructor_definition
    return []


def parse_module_id(body):
    for line in body:
        res = re.findall(r"param1.writeShort\((-*\d+)\)", line)
        if len(res) > 0:
            # print(res[0])
            return int(res[0])
        # also check for hex representation
        res = re.findall(r"param1.writeShort\(0x([abcdef\d]+)\)", line)
        if len(res) > 0:
            return int(res[0], 16)
        # also check for calculations
        res = re.findall(r"param1.writeShort\((-*\d+) \* (-*\d+)\)", line)
        if len(res) > 0:
            num1 = int(res[0][0])
            num2 = int(res[0][1])
            return num1 * num2
        # also check for calculations
        res = re.findall(r"param1.writeShort\((-*\d+) \* (-*\d+) \* (-*\d+)\)", line)
        if len(res) > 0:
            num1 = int(res[0][0])
            num2 = int(res[0][1])
            num3 = int(res[0][2])
            return num1 * num2 * num3
    raise RuntimeError("Could not parse module id for this body: {}", "\n".join(body))


def serialize_packet_base(handle: IO):
    body = read_body(handle)
    if should_skip_class(body):
        # This is probably the module registry
        print(f"Skipping file {handle.name}")
        return None
    module_name, module_base = parse_class_definition(body)
    log_debug_header(module_name)
    constants = parse_constants(body)
    constructor_definition = parse_constructor_definition(body, module_name)
    fields = parse_fields(body)
    module_id = parse_module_id(body)
    # print(f"   Constants: {constants}")
    # print("\n".join(body))
    return {
        "id": module_id,
        "initialName": module_name,  # preserve name for deobfuscation later
        "name": module_name,
        "base": module_base,
        "constants": constants,
        "constructorDefinition": constructor_definition,
        "fields": fields
    }


KNOWN_TYPES = ["boolean", "byte", "double", "float", "int", "short", "utf"]

UNSHIFTABLE_TYPES = ["boolean", "double", "float", "utf"]


def parse_field_definition_shifted(line: str, field_type):

    is_amount_calculated = line.find("%") != -1

    log_debug(f"Parsing expression: {line}")
    log_debug(f"Is amount calculated: {is_amount_calculated}")
    re_without_expr = r"(>>>|<<) (\d+) \|"
    re_with_expr = r"(>>>|<<) (\d+) \% \d+ \|"

    re_used_expr = re_with_expr if is_amount_calculated else re_without_expr

    if field_type == "int":
        # shift_operation = re.findall(r"this.(\w+) (>>>|<<) (\d+) \|", line)
        # shift_operation = re.findall(r"this.(\w+) (>>>|<<) (\d+) \% \d+ \|", line)
        shift_operation = re.findall(r"this.(\w+) "+re_used_expr, line)
    elif field_type == "short":
        # shift_operation = re.findall(r"this.(\w+) (>>>|<<) (\d+) \|", line)
        # shift_operation = re.findall(r"this.(\w+)\) (>>>|<<) (\d+) \% \d+ \|", line)
        shift_operation = re.findall(r"this.(\w+)\) "+re_used_expr, line)
    elif field_type == "arrayOfPrimitives":
        # shift_operation = re.findall(r"(_loc\d+_) (>>>|<<) (\d+) \|", line)
        # shift_operation = re.findall(r"(_loc\d+_) (>>>) (\d+)", line)
        shift_operation = re.findall(r"(_loc\d+_)\)* "+re_used_expr, line)
    else:
        # shift_operation = re.findall(r"this.(\w+)\) (>>>|<<) (\d+) \|", line)
        shift_operation = re.findall(r"this.(\w+)\) "+re_used_expr, line)
    if len(shift_operation) < 1:
        raise RuntimeError(f"Shift operation not found: {line}")
    field_name, direction, amount = shift_operation[0]
    direction = {">>>": "right", "<<": "left"}[direction]

    log_debug(f"Rotate {field_type} {amount} bits {direction}")
    return {
        "name": field_name,
        "type": field_type,
        "shiftOperationFromClientToServer":
            {
                "direction": direction,
                "amount": int(amount)
            }
    }


def parse_field_definition_unshifted(line, field_type):
    if field_type == "arrayOfPrimitives":
        name = re.findall(r"param1.write\w+\((_loc\d+_)\)", line)
    else:
        name = re.findall(r"param1.write\w+\(this.(\w+)\)", line)
    if len(name) < 1:
        raise RuntimeError(f"Could not parse name from line {line}")
    log_debug(name[0])
    return {
        "name": name[0],
        "type": field_type
    }


def parse_field_definition_shiftable(line, field_type):
    # call different parser methods whether the variable is shifted or not
    shift_matches = re.findall(r"[|<>]", line)
    if len(shift_matches) > 0:
        return parse_field_definition_shifted(line, field_type)
    return parse_field_definition_unshifted(line, field_type)


def parse_field_definition(line, field_type):
    log_debug(f"[?] parse type {field_type}")
    if field_type in UNSHIFTABLE_TYPES:
        return parse_field_definition_unshifted(line, field_type)
    return parse_field_definition_shiftable(line, field_type)


def parse_write_body(body: list):
    definitions = []
    state = "SEARCH"
    # is either byte, short or int. used to encode the length of a vector of primitives or a module
    current_field_length_type = None
    current_field = None
    log_debug_header("STATE: SEARCH")
    for line in body:
        log_code(f"\t{line}")
        if state == "SEARCH":
            if line.find("public function write") != -1:
                state = "BODY_START"
                log_debug_header("STATE: BODY_START")
            continue
        if state == "BODY_START":
            if line.find("{") != -1:
                state = "BODY_FIND_PACKET_ID"
                log_debug_header("STATE: BODY_FIND_PACKET_ID")
                continue
        if state == "BODY_FIND_PACKET_ID":
            line = line.strip()
            if line.startswith("param1.writeShort"):
                log_debug("[+] FOUND PACKET ID LINE: " + line)
                state = "BODY"
                log_debug_header("STATE: BODY")
                continue
            if len(re.findall(r"var _loc\d+_:(\*|int|Number|String|class_\d+|[A-Z]\w+) = (null|0|NaN);", line)) > 0:
                log_debug("[!] current line not yet packet id")
                continue
            raise RuntimeError(f"Unknown text: {line}")
        if state == "BODY_ARRAY_DEFINITION":
            line = line.strip()
            if len(re.findall(r"for|[{}]", line)) > 0:
                log_debug("-> skip line")
            else:
                definition = {
                    "name": current_field,
                    "length_type": current_field_length_type
                }
                # Example: _locX_.write(param1);
                if len(re.findall(r"write\(", line)) > 0:
                    definition["type"] = "arrayOfModules"
                # Example: param1.writeXXX(_locX_);
                else:
                    definition["type"] = "arrayOfPrimitives"
                    res_write_type = re.findall(r"write(\w+)", line)
                    if len(res_write_type) < 1:
                        raise RuntimeError(f"cannot parse type def for array of primitives: {line}")
                    definition["subType"] = res_write_type[0].lower()
                    res = parse_field_definition(line, definition["type"])
                    if "shiftOperationFromClientToServer" in res:
                        definition["shiftOperationFromClientToServer"] = res["shiftOperationFromClientToServer"]
                    log_debug(res)
                log_definition(definition)
                definitions.append(definition)
            if line.strip() == "}":
                state = "BODY"
                log_debug_header("STATE: BODY")
            continue
        if state == "BODY_SKIP_IF_ELSE":
            if line.find("}") > 0:
                state = "BODY"
            continue
        if state == "BODY":
            line = line.strip()
            log_debug(f"[i] {line}")

            if line.find("for each") != -1:
                state = "BODY_FOREACH"
                res_fld = re.findall(r"for each\([_\w ]+this\.([_\w]+)\)", line)
                if len(res_fld) < 1:
                    raise RuntimeError("Cannot detect variable name in for statement header")
                continue
            # TODO: while definition ?? or is this only in the read function?

            if len(re.findall(r"super\.write", line)) > 0:
                log_debug("super call found!!!")
                definitions.append(
                    {
                        "name": "super_call",
                        "type:": "super_call"
                    }
                )
                continue

            if len(re.findall(r"this\.\w+\.length", line)) > 0:
                log_debug(line)
                res = re.findall(r"param1\.write(\w+)\(this.(\w+)\.length", line)
                if len(res) < 1:
                    raise RuntimeError(f"Unable to find field name in line: {line}")
                current_field_length_type = res[0][0]
                current_field = res[0][1]
                log_debug(f"Skip line {line}")
                state = "BODY_ARRAY_DEFINITION"
                log_debug_header("STATE: BODY_ARRAY_DEFINITION")
                continue
            if len(re.findall(r"if\(", line)) > 0:
                res_fld = re.findall(r"if\([\w!= .]*this\.(\w+)[\w!= .]*\)", line)
                if len(res_fld) < 1:
                    raise RuntimeError(f"Field name not found in statement: {line}")
                current_field = res_fld[0]
                definitions.append(
                    {
                        "name": current_field,
                        "type:": "submodule"
                    }
                )
                state = "BODY_SKIP_IF_ELSE"
                continue
            if line.find("else") != -1:
                state = "BODY_SKIP_IF_ELSE"
                continue
            # single line
            if re.findall("param1", line):
                field_type = re.findall(r"write(\w+)", line)
                if len(field_type) < 1:
                    raise RuntimeError(f"could not identify type: {line}")
                field_type = field_type[0].lower()
                if field_type not in KNOWN_TYPES:
                    raise RuntimeError(f"Unknown type: {field_type}")
                definition = parse_field_definition(line, field_type)
                log_definition(definition)
                definitions.append(definition)
                continue
            continue
        raise RuntimeError(f"Unhandled state: {state}")
    return definitions


def serialize_packet_config(handle: IO):
    body = read_body(handle)  # mothafucka
    # nobody likes this warning
    x = 9
    if should_skip_class(body):
        # This is probably the module registry
        print(f"Skipping file {handle.name}")
        return None
    module_name, module_base = parse_class_definition(body)
    log_debug_header(module_name)
    constants = parse_constants(body)
    constructor_definition = parse_constructor_definition(body, module_name)
    fields = parse_fields(body)
    module_id = parse_module_id(body)
    write_body = parse_write_body(body)
    # print(f"   Constants: {constants}")
    # print("\n".join(body))
    return {
        "id": module_id,
        "initialName": module_name,  # preserve name for deobfuscation later
        "name": module_name,
        "base": module_base,
        "constants": constants,
        "constructorDefinition": constructor_definition,
        "fields": fields,
        "writeBody": write_body
    }
