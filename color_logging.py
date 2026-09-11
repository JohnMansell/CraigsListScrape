import inspect
import logging
import logging.config
import logging.handlers
import os
import json
import selenium

from rich.traceback import install
from rich.logging import RichHandler

import argparse

# -----------------------------
#       Global Args
# -----------------------------
GLOBAL_ARGS = dict()


def parse_args():
    parser = argparse.ArgumentParser(description="Spartan Super Resolution Web Server")
    parser.add_argument('--log',
                        dest='log_level',
                        type=str,
                        default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Set the logging level')

    args = parser.parse_args()
    GLOBAL_ARGS['log_level'] = args.log_level


parse_args()


# -----------------------------
#       Config
# -----------------------------

# --- Level
level_config = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

log_level = level_config[GLOBAL_ARGS['log_level'].lower()]

# --- Path
LOGDIR = os.environ.get('CRAIGSLIST_LOGDIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs'))
if not os.path.exists(LOGDIR):
    os.makedirs(LOGDIR)

LOG_FILENAME = LOGDIR + '/craigslist.log'
FORMAT = "Thread[%(threadName)s] %(module)-15s::%(funcName)10s %(levelname)8s ::[ %(lineno)3s ] %(message)s"
logging.basicConfig(
        level=log_level,
        format=FORMAT,
        datefmt="[%X]")


# ToDo: should be a better place for this, but logging is basically a universal module, so it ended up here for now
MYPID = os.getpid()


# --------------------------------------
#           Get Logger
# --------------------------------------
def get_logger(name, console_level=log_level, file_level=log_level) -> logging.Logger:

    # --- Log Path
    calling_file_path = inspect.stack()[1].filename
    calling_dir = os.path.dirname(calling_file_path)
    filename = 'server.log' if 'backend' in calling_dir else 'client.log'
    log_file_path = os.path.join(LOGDIR, filename)

    # --- Logger
    new_logger = logging.getLogger(name)
    new_logger.handlers = []
    new_logger.propagate = False

    # --- Handlers
    stream_handler = RichHandler(rich_tracebacks=True, tracebacks_show_locals=True, tracebacks_suppress=[selenium])
    file_handler = logging.handlers.TimedRotatingFileHandler(filename=log_file_path, when="midnight", backupCount=10)

    # --- Format
    file_handler.setFormatter(logging.Formatter(FORMAT))

    # --- Level
    stream_handler.setLevel(console_level)
    file_handler.setLevel(file_level)

    # --- Add Handlers
    new_logger.addHandler(stream_handler)
    new_logger.addHandler(file_handler)

    return new_logger


# --------------------------------------
#           Line Break
# --------------------------------------
def line_break(message, line='-'):
    to_print = '\n\n' + line * 40 + '\n'
    to_print += ' ' * 5 + message + '\n'
    to_print += line * 40 + '\n'
    return to_print


# --------------------------------------
#           Dictionary Format
# --------------------------------------
def dumps(dict_object: dict, name=None):

    # ToDo -- Make this output a single line for lists less that ~3 items long
    # l_string = json.dumps(dict_object, indent=4)
    # l_string2 = re.sub(r'": \[\s+', '": [', l_string)
    # l_string3 = re.sub(r'",\s+', '", ', l_string2)
    # l_string4 = re.sub(r'"\s+\]', '"]', l_string3).replace('\n', '\n' + " " * 55 + '| ')

    if name is None:
        name = inspect.stack()[1].function

    r_string = f'--- {name} ---\n' + " " * 55 + '| '
    l_string = json.dumps(dict_object, indent=4).replace('\n', '\n' + " " * 55 + '| ')

    return r_string + l_string
