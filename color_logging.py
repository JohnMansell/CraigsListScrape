import inspect
import sys
import logging
import logging.config
import logging.handlers
import os
import argparse
import json
import copy




# -----------------------------
#       Config
# -----------------------------

# --- Argparse
parser = argparse.ArgumentParser()
parser.add_argument('--log', action='store', required=False, default='info')
args, unknown = parser.parse_known_args()

# --- Level
level_config = {'debug': logging.DEBUG,
                'info': logging.INFO,
                'warning': logging.WARNING,
                'error': logging.ERROR}

log_level = level_config[args.log]

# --- Path
LOGDIR = '/var/log/craigslist'
if not os.path.exists(LOGDIR):
    os.makedirs(LOGDIR)

LOG_FILENAME = LOGDIR + '/craigslist.log'
logging.basicConfig(
    level=log_level,
    format='%(levelname)s - %(asctime)s - %(name)s - %(message)s'
)

# ToDo: should be a better place for this, but logging is basically a universal module, so it ended up here for now
MYPID = os.getpid()

# --------------------------------------
#           Color Format
# --------------------------------------
BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)

# Background = 40 + [color]
# Foreground = 30

#These are the sequences need to get colored ouput
RESET_SEQ = "\033[0m"
COLOR_SEQ = "\033[1;%dm"
BOLD_SEQ = "\033[1m"
COLORS = {
    'WARNING': YELLOW,
    'INFO': WHITE,
    'DEBUG': BLUE,
    'CRITICAL': YELLOW,
    'ERROR': RED
}


# --------------------------------------
#           Color Format
# --------------------------------------
class ColoredFormatter(logging.Formatter):

    def __init__(self, format_string):
        logging.Formatter.__init__(self, format_string)

    # @staticmethod
    # def formatter_message(message):
    #     return message.replace("$RESET", RESET_SEQ).replace("$BOLD", BOLD_SEQ)

    def format(self, record):
        levelname = record.levelname
        message = record.msg
        message = str(message) if message else "None"

        rcd_copy = copy.copy(record)
        if levelname in COLORS:

            # --- Level Name
            levelname_color = (COLOR_SEQ % (30 + COLORS[levelname])) + levelname + RESET_SEQ
            rcd_copy.levelname = levelname_color

            # --- Message
            if levelname in ['WARNING', 'ERROR', 'CRITICAL']:
                message_color = (COLOR_SEQ % (30 + COLORS[levelname])) + message + RESET_SEQ
                rcd_copy.msg = message_color

        return logging.Formatter.format(self, rcd_copy)


# --------------------------------------
#           Get Logger
# --------------------------------------
def get_logger(name, level=log_level):

    # --- Logger
    new_logger = logging.getLogger(name)
    new_logger.handlers = []
    new_logger.propagate = False

    # --- Handlers
    stream_h = logging.StreamHandler(sys.stdout)
    file_h = logging.handlers.TimedRotatingFileHandler(filename=LOG_FILENAME, when='midnight', backupCount=10)

    # --- Format
    format_string = "%(asctime)s| %(module)-18s [ %(lineno)3s ] ::  %(levelname)8s :: %(message)s"
    time_format   = "%y-%m-%d %H:%M:%S"
    s_formatter = ColoredFormatter(format_string)
    f_formatter = logging.Formatter(format_string)
    stream_h.setFormatter(s_formatter)
    file_h.setFormatter(f_formatter)

    # --- Level
    stream_h.setLevel(level)
    file_h.setLevel(level)

    # --- Add handlers
    new_logger.addHandler(stream_h)
    new_logger.addHandler(file_h)

    print(f"Creating new logger : {name} - {logging.getLevelName(new_logger.getEffectiveLevel())}")

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
