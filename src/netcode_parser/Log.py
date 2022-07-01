debug_enabled = False
code_log_enabled = False
definitions_enabled = False


def log_info(text, prefix="\t"):
    print(prefix, text)


def log_debug(text, prefix="\t"):
    if debug_enabled:
        print(prefix, text)


def log_definition(text):
    if definitions_enabled:
        log_info(text)


def log_code(text, prefix="-"*12):
    if code_log_enabled:
        print(prefix, text.strip())


def log_info_header(text):
    log_info(text, "")


def log_debug_header(text):
    log_debug(text, "")
