import re
from typing import IO

from DONetcodeParserLog import *


# read all lines into a list and trim newlines
def read_body(handle: IO) -> list:
    return [line.replace("\r", "").replace("\n", "") for line in handle.readlines()]


def find_class_def_line(body) -> str:
    for line in body:
        if str(line).find("public class") > 0:
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
        if line.find("const const") > 0:
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
        if line.find("Not decompiled") > 0:
            return True
    return False


def parse_fields(body: list) -> list:
    fields = []
    for line in body:
        res = re.findall(r"public var (\w+):([\w<>.]+)", line)
        if len(res) < 1:
            continue
            # raise RuntimeError(f"could not parse field definition in line {line}")
        field = {"name": res[0][0], "initialName": res[0][0], "type": res[0][1]}
        fields.append(field)
    return fields


def parse_constructor_definition(body, module_name):
    for line in body:
        if line.find(f"function {module_name}") > 0:
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
            return res[0]
    raise RuntimeError("Could not parse module id: {}", "\n".join(body))


def serialize_packet_base(handle: IO):
    body = read_body(handle)
    if should_skip_class(body):
        # This is probably the module registry
        print(f"Skipping file {handle.name}")
        return None
    module_name, module_base = parse_class_definition(body)
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


KNOWN_TYPES = ["Boolean", "Byte", "Double", "Float", "Int", "Short", "UTF"]

UNCHANGED_TYPES = ["Boolean", "Byte", "Double", "Float", "UTF"]


def parse_field_definition_shifted(line, field_type):
    shift_operation = re.findall(r"this.(\w+) (>>>|<<) (\d+) \|", line)
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
                "amount": amount
            }
    }


def parse_field_definition_unshifted(line, field_type):
    name = re.findall(r"param1.write\w+\(this.(\w+)\)", line)
    if len(name) < 1:
        raise RuntimeError(f"Could not parse name from line {line}")
    log_debug(name[0])
    return {
        "name": name[0],
        "type": field_type
    }


def parse_field_definition_of_changeable_type(line, field_type):
    # call different parser methods whether the variable is shifted or not
    shift_matches = re.findall(r"[|<>]", line)
    if len(shift_matches) > 0:
        return parse_field_definition_shifted(line, field_type)
    return parse_field_definition_unshifted(line, field_type)


def parse_field_definition(line, field_type):
    log_debug(f"[?] parse type {field_type}")
    if field_type in UNCHANGED_TYPES:
        return parse_field_definition_unshifted(line, field_type)
    return parse_field_definition_of_changeable_type(line, field_type)


def parse_write_body(body: list):
    definitions = []
    state = "SEARCH"
    current_field = None
    log_debug_header("STATE: SEARCH")
    for line in body:
        log_code(f"\t{line}")
        if state == "SEARCH":
            if line.find("public function write") > 0:
                state = "BODY_START"
                log_debug_header("STATE: BODY_START")
                continue
        if state == "BODY_START":
            if line.find("{"):
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
            if len(re.findall(r"var _loc\d+_:\* = null;", line)) > 0:
                log_debug("[!] current line not yet packet id")
                continue
            raise RuntimeError(f"Unknown text: {line}")
        if state == "BODY_ARRAY_DEFINITION":
            line = line.strip()
            if len(re.findall(r"for|[{}]", line)) > 0:
                log_debug("-> skip line")
            else:
                if len(re.findall(r"write\(", line)) > 0:
                    definition = {
                        "name": current_field,
                        "type": "arrayOfModules"
                    }
                    log_definition(definition)
                    definitions.append(definition)
                else:
                    log_debug("not a module")
            if line.strip() == "}":
                state = "BODY"
                log_debug_header("STATE: BODY")
            continue
        if state == "BODY":
            line = line.strip()
            log_debug(f"[i] {line}")
            # TODO: for definition
            # TODO: while definition
            # TODO: if definition
            # TODO: detect length encoding => for loop

            if len(re.findall(r"\.length", line)) > 0:
                log_debug(line)
                res = re.findall(r"this.(\w+)", line)
                if len(res) < 1:
                    raise RuntimeError(f"Unable to find field name in line: {line}")
                current_field = res[0]
                log_debug(f"Skip line {line}")
                state = "BODY_ARRAY_DEFINITION"
                log_debug_header("STATE: BODY_ARRAY_DEFINITION")
                continue
            if len(re.findall("if", line)) > 0:
                STATE = "BODY_IF"
                # TODO: find target field
                continue
            # single line
            if re.findall("param1", line):
                field_type = re.findall(r"write(\w+)", line)
                if len(field_type) < 1:
                    raise RuntimeError(f"could not identify type: {line}")
                field_type = field_type[0]
                if field_type not in KNOWN_TYPES:
                    raise RuntimeError(f"Unknown type: {field_type}")
                definition = parse_field_definition(line, field_type)
                log_definition(definition)
                definitions.append(definition)
                continue
            pass


def serialize_packet_config(handle: IO):
    body = read_body(handle)  # mothafucka
    # nobody likes this warning
    x = 9
    if should_skip_class(body):
        # This is probably the module registry
        print(f"Skipping file {handle.name}")
        return None
    module_name, module_base = parse_class_definition(body)
    constants = parse_constants(body)
    constructor_definition = parse_constructor_definition(body, module_name)
    fields = parse_fields(body)
    module_id = parse_module_id(body)
    parse_write_body(body)
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
