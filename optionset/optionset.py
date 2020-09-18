#!/usr/bin/env python3
"""
Optionset
~~~~~~~~

Enable/disable user-predefined options in text-based dictionaries.
Use -h to view help.

Author: Matthew C. Jones
Email: matt.c.jones.aoe@gmail.com

:copyright: 2020 by Optionset authors, see AUTHORS for more details.
:license: GPLv3, see LICENSE for more details.
"""

# Import files
import argparse
import logging
import os
import re

from collections import defaultdict, namedtuple, OrderedDict
from configparser import ConfigParser
from contextlib import contextmanager
from fnmatch import fnmatch
from functools import wraps
from pathlib import Path
from pprint import pformat
from sys import argv, exit
from time import time

__author__ = "Matthew C. Jones"
__version__ = "20.09"

__all__ = (
        "optionset",
        "__author__",
        "__version__",
        )

# ############################################################ #
# Set up input argument parser
# ############################################################ #
BASENAME = Path(__file__).name
BASHCOMPCMD = 'os'  # bash-completion run command
BASENAME_NO_EXT = Path(__file__).stem
RUNCMD = BASHCOMPCMD if '--bash-ompletion' in argv else BASENAME
AUX_DIR = Path("~/.optionset").expanduser()
LOG_NAME = f"log.{BASENAME}"
BASHCOMP_NAME = "bash_completion"
CONFIG_NAME = f"{BASENAME_NO_EXT}.cfg"
BASH_FUNC_STR = f"""function {BASHCOMPCMD} {{
    {BASENAME} "$@" --bash-completion;
    source {AUX_DIR/BASHCOMP_NAME};
    }}"""
SHORT_DESCRIPTION = f"""
This program enables and disables user-predefined options in text-based code
and dictionary files in the base directory and below.  The user specifies the
lines in the files that will either be enabled or disabled by adding macro
commands as commented text.
"""
SHORT_HELP_DESCRIPTION = f"""{SHORT_DESCRIPTION}
Run '{RUNCMD} --help-full' to view more-detailed help"""
FULL_HELP_DESCRIPTION = f"""{SHORT_DESCRIPTION}
For example, the OpenFOAM dictionary text file 'system/controlDict' could be
written as,

application pimpleFoam // @simulation transient
//application simpleFoam // @simulation steady

This setup allows the user to easily switch between transient and steady
simulations without manually editting the file.  Simply run,

{RUNCMD} @simulation steady

and the dictionary file will be modified and re-written as,

//application pimpleFoam // @simulation transient
application simpleFoam // @simulation steady

where the steady solver 'simpleFoam' is now uncommented and active. Here
@simulation is the 'option' while transient and steady are the 'settings'.
An unlimited number of unique options and settings are allowed.  Each can only
be composed of alphanumerical words with dots, pluses, minuses, and
underscores. Note that the first one or more characters in a option must be a
special symbol (non-bracket, non-comment-indicator, non-option/setting) such as
'~@$^&=|?'.

Use '{RUNCMD} -a ' to view all of the options that you have set, or even
'{RUNCMD} -a @simple' to view all options that begin with '@simple'.

To avoid comment clutter, multi-line options are encouraged by writing * in
front of the first and last options in a series (see text on left),

functions        // *@forces on    | <---  |   functions        // @forces on
{{                                  |INSTEAD|   {{                // @forces on
#include "forces"                  |  OF   |   #include "forces"// @forces on
}}                // *@forces on    | --->  |   }}                // @forces on
//               // @forces off    |       |   //               // @forces off

An additional feature is a variable option.  For variable options the
dictionary text file must be formatted with a Perl-styled regular expression
='<regex>' that matches the desired text to be changed such as,

variable option = 5.5; // @varOption ='= (.*);'

To change 'variable option' to 6.7 use, '{RUNCMD} @varOption 6.7'.
The file becomes,

variable option = 6.7; // @varOption ='= (.*);'

To enable Bash tab completion add the following line to '~/.bashrc':

{BASH_FUNC_STR}

and run this program using '{BASHCOMPCMD}' instead of '{BASENAME}'

Using your favorite scripting language, it is convenient to glue this program
into more advanced option variation routines to create advanced parameter
sweeps and case studies.  Note that it is possible to directly import this
funtionality into a Python script using 'from optionset import optionset' and
feeding an array of command line arguments to the optionset() function.
"""
EPILOG = ""  # display after argument help

parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog=RUNCMD, description=SHORT_HELP_DESCRIPTION, epilog=EPILOG)
parser.add_argument(
        'option', metavar='option', nargs='?', type=str, default="",
        help='\'option\' name')
parser.add_argument(
        'setting', metavar='setting', nargs='?', type=str, default="",
        help='\'setting\' for given \'option\'')
parser.add_argument(
        '-H', '--help-full', dest='helpFull', default=False,
        action='store_true',
        help=f"show full help message and exit")
parser.add_argument(
        '-a', '--available', dest='available', default=False,
        action='store_true',
        help=("show available option-setting combinations; "
              "allows for unix-style glob-expression searching; "
              "'-a' is implicitely enabled when no 'setting' is input"))
parser.add_argument(
        '-f', '--show-files', dest='showFiles', default=False,
        action='store_true',
        help=f"show files associate with available options")
parser.add_argument(
        '-v', '--verbose', dest='verbose', default=False, action='store_true',
        help="turn on verbose output")
parser.add_argument(
        '-q', '--quiet', dest='quiet', default=False, action='store_true',
        help="turn off all standard output")
parser.add_argument(
        '-d', '--debug', dest='debug', default=False, action='store_true',
        help="turn on debug output in log file")
parser.add_argument(
        '-n', '--no-log', dest='noLog', default=False, action='store_true',
        help=f"do not write log file to '{AUX_DIR/LOG_NAME}'")
parser.add_argument(
        '--bash-completion', dest='bashCompletion', default=False,
        action='store_true',
        help=("auto-generate bash tab-completion script "
              f"'{AUX_DIR/BASHCOMP_NAME}'"))
parser.add_argument(
        '--version', dest='version', default=False, action='store_true',
        help="show version and exit")
parser.add_argument(
        '--auxillary-dir', dest='auxDir', type=str,
        default=AUX_DIR, help=argparse.SUPPRESS)

# Initialize global variables
IGNORE_DIRS = ['.[a-zA-Z0-9]*', '__pycache__', '[0-9]', '[0-9][0-9]*',
               '[0-9].[0-9]*', 'log', 'logs', 'processor[0-9]*', 'archive',
               'trash',
               ]  # UNIX-based wild cards
IGNORE_FILES = [BASENAME, CONFIG_NAME, LOG_NAME, '.*', 'log.*', '*.log',
                '*.py', '*.pyc', '*.gz', '*.png', '*.jpg', '*.obj', '*.stl',
                '*.stp', '*.step',
                ]  # UNIX-based wild cards
MAX_FLINES = 9999  # maximum lines per file
MAX_FSIZE_KB = 10  # maximum file size, kilobytes

# Regular expression frameworks
ANY_COMMENT_IND = r'(?:[#%!]|//|--)'  # comment indicators: # % // -- !
MULTI_TAG = r'[*]'  # for multi-line commenting
ANY_WORD = r'[a-zA-Z0-9._\-\+]+'
ANY_RAW_OPTION = ANY_WORD
ANY_QUOTE = r'[\'"]'
ANY_VAR_SETTING = rf'\={ANY_QUOTE}.+{ANY_QUOTE}'
ANY_SETTING = rf'(?:{ANY_WORD}|{ANY_VAR_SETTING})'
VALID_INPUT_SETTING = rf'(?: |{ANY_WORD})+'  # words with spaces (using '')
BRACKETS = r'[()<>\[\]]'
# Implicitely match tag. Do not include any of these:
ANY_TAG = rf'(?:(?!\s|{ANY_COMMENT_IND}|{MULTI_TAG}|{ANY_WORD}|{BRACKETS}).)'
# Explicitely specify tag with: ANY_TAG = r'[~@$^&\=\|\?]'
WHOLE_COMMENT = (r'(?P<comInd>{comInd})'
                 r'(?P<wholeCom>.*\s+{mtag}*{tag}+{rawOpt}\s+{setting}\s.*\n?)'
                 )
UNCOMMENTED_LINE = (r'^(?P<nestedComInds>{nestedComInds})'
                    r'(?P<nonCom>\s*(?:(?!{comInd}).)+)' + WHOLE_COMMENT)
COMMENTED_LINE = (r'^(?P<nestedComInds>{nestedComInds})'
                  r'(?P<nonCom>\s*{comInd}(?:(?!{comInd}).)+)' + WHOLE_COMMENT)
ONLY_OPTION_SETTING = r'({mtag}*)({tag}+)({rawOpt})\s+({setting})\s?'
GENERIC_RE_VARS = {'comInd': ANY_COMMENT_IND, 'mtag': MULTI_TAG,
                   'tag': ANY_TAG, 'rawOpt': ANY_RAW_OPTION,
                   'setting': ANY_SETTING, 'nestedComInds': ''}

# Error messages
INCOMPLETE_INPUT_MSG = f'''InputError:
Incomplete input. Try:
    "{RUNCMD} -h"                    to view help
    "{RUNCMD} -a"                    to view available options
    "{RUNCMD} -a <unix expression>"  to search options using a unix expression
    "{RUNCMD} <option> <setting>"    to set the <setting> of <option>'''
INVALID_OPTION_MSG = f'''InputError:
Invalid option name. A preceding tag, such as '@' in '@option' is required, and
the rest of the option must adhere to the following regular expression:
{ANY_WORD}
To view help try:
    "{RUNCMD} -h"'''
INVALID_SETTING_MSG = f'''InputError:
Invalid setting name. The setting name must adhere to the following regular
expression: {ANY_WORD}
To view help try:
    "{RUNCMD} -h"'''
INVALID_VAR_REGEX_MSG = r'''FormatError:
Invalid 'variable setting' regular expression. The commented regular expression
must adhere to this form: %(anyVar)s
(e.i. an equals sign followed by a user specified regular expression in quotes)
Additionally, the corresponding code on the line of this 'variable setting'
must match the user specified regular expression in quotes. This regular
expression must have one and only one set of parentheses surrounding the
variable option to be matched such as '(.*)'.  Otherwise, To specify literal
parentheses in the regex, use '\('.
\r\nFile:{fileName}
Line {lineNum}:{line}
To view help try:
    "%(runCmd)s -h"''' % {'anyVar': ANY_VAR_SETTING, 'runCmd': RUNCMD}
INVALID_REGEX_GROUP_MSG = '''InvalidRegexGroupError: {specificProblem}
A regular expression 'group' is denoted by a surrounding pair of parentheses
'()' The commented variable setting should be the only group.' Use '()' to
surround only the variable setting group in the commented regular expression.
'''

# ############################################################ #
# Define classes
# ############################################################ #


class FileVarsDatabase:
    """Data structure to hold variables used in file processing.
       Input file path, user input structure, and comment index.
    """
    def __init__(self, filePath, inputDb):
        """Initialize variables. """
        self.filePath = filePath
        self.inputDb = inputDb

        self.F_fileModified = False  # True if file is modified
        self.F_multiLineActive = False  # if active, toggle line
        self.F_multiCommented = None  # True if multi-line option is commented
        self.nestedLvl = 0  # +1 level every commented multi-line option
        self.nestedIncrement = 0  # increments the nested level

        # Get string that signifies a commented line
        self.comInd = _get_comment_indicator(filePath)

        # Prepare regular expressions
        self.reVars = GENERIC_RE_VARS
        self.reVars['comInd'] = self.comInd  # set file-specific indicator

        # Prepare nested option database
        self.nestedOptionDb = OrderedDict()


# ############################################################ #
# Define utility functions
# ############################################################ #

def _print_and_log(printStr):
    """Print to standard out and INFO level in log. """
    logging.info(printStr)
    if not F_QUIET:
        print(printStr)


def _log_before_after_commenting(func):
    """Wrapper to add file modifications to the log file. """
    @wraps(func)
    def log(*args_, **kwargs):
        lineBeforeMod = '[{:>4} ]{}'.format(args_[2], args_[0].rstrip('\r\n'))
        returnStr = func(*args_, **kwargs)
        lineAfterMod = '[{:>4}\']{}'.format(args_[2], returnStr.rstrip('\r\n'))
        if F_VERBOSE:
            _print_and_log(lineBeforeMod)
            _print_and_log(lineAfterMod)
        else:
            logging.info(lineBeforeMod)
            logging.info(lineAfterMod)
        return returnStr
    return log


@_log_before_after_commenting
def _uncomment(line, comInd, lineNum):
    """Uncomment a line. Input requires comment indicator string. """
    line = re.sub(rf'^(\s*)({comInd})', r"\1", line)
    return line


@_log_before_after_commenting
def _comment(line, comInd, lineNum):
    """Comment a line. Input requires comment indicator string. """
    line = comInd + line
    return line


@contextmanager
def _handle_errors(errTypes, msg):
    """Use 'with:' to handle an error and print a message. """
    try:
        yield
    except errTypes as e:
        _print_and_log(msg)
        exit()


def _write_bash_completion_file(opsDb, varOpsDb,
                               bashCompPath=AUX_DIR/BASHCOMP_NAME):
    """Write file that can be sourced to enable tab completion for this tool.
    """
    usageStr = parser.format_usage()
    helpStr = parser.format_help()
    reShortUsage = re.compile(rf"\s(-\w+)")
    reLongUsage = re.compile(rf"\s(--[a-zA-Z\-]+)")
    defaultCmdOptsShort = [
            f"'{opt}'" for opt in sorted(reShortUsage.findall(helpStr))]
    defaultCmdOptsLong = [
            f"'{opt}'" for opt in sorted(reLongUsage.findall(helpStr))]
    defaultCmdOptsShortStr = ' '.join(defaultCmdOptsShort)
    defaultCmdOptsLongStr = ' '.join(defaultCmdOptsLong)
    fileContentsTemplate = r"""#!/bin/bash
# Auto-generated Bash completion settings for {baseRunCmd}
# Run 'source {bashCompPath}' to enable
optRegex="\-[a-z], --[a-z]*"
_optionset()
{{
    local cur prev

    cur=${{COMP_WORDS[COMP_CWORD]}}
    prev=${{COMP_WORDS[COMP_CWORD-1]}}

    case ${{COMP_CWORD}} in
        1)
            COMPREPLY=($(compgen -W "
                {defaultCmdOptsShortStr}
                {defaultCmdOptsLongStr}{gatheredOptionsStr}
                " -- ${{cur}}))
            ;;
        2)
            case ${{prev}} in {optionsWithSettingsStr}
            esac
            ;;
        *)
            COMPREPLY=()
            ;;
    esac
}}
complete -F _optionset {bashCompCmd}
complete -F _optionset {bashCompCmdB}"""
    gatheredOptionsStr = ""
    optionsWithSettingsTemplate = """
                {optionStr})
                    COMPREPLY=($(compgen -W "'{settingsStr}'" -- ${{cur}}))
                    ;;"""
    optionsWithSettingsStr = ""
    bashCompCmd = BASHCOMPCMD
    bashCompCmdB = BASENAME_NO_EXT
    baseRunCmd = BASENAME

    for db in (opsDb, varOpsDb):
        for item in sorted(db.items()):
            optionStr = item[0].replace(r'$', r'\$')
            gatheredOptionsStr += os.linesep + f"                '{optionStr}'"
            settingsStr = ""
            for subItem in sorted(item[1].items()):
                settingStr = subItem[0]
                settingsStr += " " + settingStr
            optionsWithSettingsStr += \
                optionsWithSettingsTemplate.format(**locals())

    fileContents = fileContentsTemplate.format(**locals())

    # Add convenient debug command that references in-development code
    if logging.getLevelName(logging.root.level) == "DEBUG":
        fileContents += "complete -F _optionset debug_os"

    with open(bashCompPath, 'w', encoding='UTF-8') as file:
        logging.info(f"Writing Bash completion settings to {bashCompPath}")
        file.writelines(fileContents)


def _print_available(opsDb, varOpsDb, showFilesDb, globPat='*'):
    """Print available options and options for use; optionally sort with unix
    expression. """
    bodyMsg = ""
    for db in (opsDb, varOpsDb):
        logging.info(pformat(db, indent=1))
        for item in sorted(db.items()):
            if not fnmatch(item[0], globPat):
                continue
            optionStr = item[0]
            bodyMsg += os.linesep + f"  {optionStr}"
            for subItem in sorted(item[1].items()):
                settingStr = subItem[0]
                if subItem[1] is True:
                    leftStr, rightStr = '>', '<'
                elif subItem[1] is False:
                    leftStr, rightStr = ' ', ' '
                elif subItem[1] is None:
                    leftStr, rightStr = ' ', ' '
                elif subItem[1] is not None:
                    leftStr, rightStr = subItem[1], subItem[1]
                else:
                    leftStr, rightStr = '?', '?'
                bodyMsg += os.linesep + f"\t{leftStr} {settingStr} {rightStr}"
            if showFilesDb is not None:
                if showFilesDb[optionStr]:
                    filesStr = ' '.join(showFilesDb[optionStr].keys())
                    bodyMsg += os.linesep + "  " + filesStr + os.linesep
                    bodyMsg += "-"*60

    subHdrMsg = r"('  inactive  ', '> active <', '? both ?', '= variable =')"
    if bodyMsg == "":
        hdrMsg = "No available options and settings matching '{globPat}'"
    else:
        hdrMsg = "Showing available options and settings matching '{globPat}'"
        hdrMsg += os.linesep + subHdrMsg
    fullMsg = hdrMsg.format(globPat=globPat) + bodyMsg
    _print_and_log(fullMsg)


def _add_left_right_groups(inLineRe):
    r"""Add left and right groups to regex.
    For example: \( (.*) 0 0 \) becomes (\( )(.*)( 0 0 \)) """
    # Must add one to get rid of preceding character match
    leftParenInd = re.search(r'[^\\]([\(])', inLineRe).start() + 1
    rightParenInd = re.search(r'[^\\]([\)])', inLineRe).start() + 1
    left = inLineRe[:leftParenInd]
    mid = inLineRe[leftParenInd:rightParenInd + 1]
    right = inLineRe[rightParenInd + 1:]
    newInLineRe = f"({left}){mid}({right})"
    return newInLineRe


@_log_before_after_commenting
def _set_var_option(line, comInd, lineNum, strToReplace, setting,
                    nestedComInds, nonCom, wholeCom):
    """Return line with new variable option set. """
    # Add 2 new groups, one for the left side and the other for the right
    inLineRe = _strip_setting_regex(setting)
    logging.info(f"Setting variable option:{inLineRe}:{strToReplace}")
    newInLineRe = _add_left_right_groups(inLineRe)

    def replace_F(m):
        return m.group(1) + strToReplace + m.group(3)
    newNonCom = re.sub(newInLineRe, replace_F, nonCom)
    newLine = nestedComInds + newNonCom + comInd + wholeCom
    return newLine


def _skip_file_warning(fileName, reason):
    """Log a warning that the current file is being skipped. """
    logging.warning(f"Skipping: {fileName}")
    logging.warning(f"Reason: {reason}")


def _yield_utf8(file):
    """Yield file lines only if they are UTF-8 encoded (non-binary). """
    try:
        for line in file:
            yield line
    except UnicodeDecodeError as err:
        _skip_file_warning(file.name, err)


def _line_count(fileName, lineLimit):
    """Return number of lines in a file unless file exceeds line limit. """
    lineCount = 0
    with open(fileName, 'r', encoding='UTF-8') as file:
        for line in _yield_utf8(file):
            lineCount += 1
            if lineCount > lineLimit:
                return lineCount + 1  # return line limit +1
    return lineCount


def _get_comment_indicator(fileName):
    """Get comment indicator from fileName ('#', '%', '!', '//', or '--'). """
    with open(fileName, 'r', encoding='UTF-8') as file:
        commdLineRe = re.compile(rf'^\s*({ANY_COMMENT_IND}).*')
        for line in _yield_utf8(file):
            searchCommdLine = commdLineRe.search(line)
            if searchCommdLine:
                return searchCommdLine.group(1)

        logging.debug('Comment not found at start of line. Searching in-line.')
        unCommdLineRe = re.compile(UNCOMMENTED_LINE.format(**GENERIC_RE_VARS))
        file.seek(0)  # restart file
        for line in _yield_utf8(file):
            searchUnCommdLine = unCommdLineRe.search(line)
            if searchUnCommdLine:
                return searchUnCommdLine.group('comInd')


def _check_varop_groups(reStr):
    """Calculate the number of regex groups designated by (). """
    allGroups = re.findall(r'([^\\]\(.*?[^\\]\))', reStr)
    if allGroups:
        if len(allGroups) > 1:
            _print_and_log(INVALID_REGEX_GROUP_MSG.format(
                specificProblem='More than one regex group \'()\' found'))
            raise AttributeError
        else:
            pass
    else:
        _print_and_log(INVALID_REGEX_GROUP_MSG.format(
            specificProblem='No regex groups found.\r\n'))
        raise AttributeError


def _strip_setting_regex(settingStr):
    """Return in-line regular expression using setting."""
    return settingStr[2:-1]  # remove surrounding =''


def _parse_inline_regex(nonCommentedText, setting, varErrMsg=""):
    """Parse variable option value using user-defined regular expression
    stored in 'setting'.
    """
    # Attribute handles regex fail. Index handles .group() fail
    with _handle_errors(errTypes=(AttributeError, IndexError, re.error),
                        msg=varErrMsg):
        inLineRe = _strip_setting_regex(setting)
        _check_varop_groups(inLineRe)
        strToReplace = re.search(inLineRe, nonCommentedText).group(1)
    return strToReplace


def _process_line(line, lineNum, fDb, optionsSettingsDb, varOptionsValuesDb,
                  showFilesDb):
    """Apply logic and process options/settings in a single line of the current
    file.  This is the heart of the code.

    Terminology is explained by referring to the following example lines,

    // somefile.txt start of file
    Some code here. // some comment here @optionA settingA
    //Some            // nestedLvl is 0 here *@optionA settingB
    //other           // nestedLvl is 1 here
    //code            // nestedLvl is 1 here @optionB settingA
    //here.           // nestedLvl is 0 here *@optionA settingB
    Final code.     // nestedLvl is 0 here @optionB settingB
    End of file.

    comInd:     '//' is extracted comment indicator; this denotes a comment
    option:     '@optionA' and '@optionB' are extracted options
    tag:        '@' is the extracted tag for '@optionA' and '@optionB'
    rawOpt:     'optionA' and 'optionB' are the extracted raw options
    setting:    'settingA' and 'settingB' are extracted settings
    mtag:       '*' is the multi-tag, which indicates a multi-line option, in
                this case for '@optionA settingB'
    nestedLvl:  '0' is starting level; when a multi-line option is found, the
                nestedLvl is increased by 1. '@optionB' is a nested option
                because it lies within the multi-line '@optionA settingB'
    (in)active: An option-setting combination on an uncommented line is active.
                Nested options also account for the nested level. In the above
                example, '@optionA settingA' and '@optionB settingB' are
                active, while '@optionA settingB' and '@optionB settingB' are
                inactive.
    """
    newLine = line
    inp = fDb.inputDb
    varErrMsg = INVALID_VAR_REGEX_MSG.format(fileName=fDb.filePath,
                                             lineNum=lineNum, line=line)

    # Adjust nested level
    fDb.nestedLvl += fDb.nestedIncrement
    fDb.nestedIncrement = 0  # reset
    fDb.reVars['nestedComInds'] = rf"\s*{fDb.comInd}" * fDb.nestedLvl

    # Identify components of line based on regular expressions
    commdLineRe = re.compile(COMMENTED_LINE.format(**fDb.reVars))
    unCommdLineRe = re.compile(UNCOMMENTED_LINE.format(**fDb.reVars))
    tagOptionSettingRe = re.compile(ONLY_OPTION_SETTING.format(**fDb.reVars))
    commdLineMatch = commdLineRe.search(line)
    unCommdLineMatch = unCommdLineRe.search(line)
    if commdLineMatch:  # must search for commented before uncommented
        nestedComInds, nonCom, wholeCom =\
                commdLineMatch.group('nestedComInds', 'nonCom', 'wholeCom')
    elif unCommdLineMatch:
        nestedComInds, nonCom, wholeCom =\
                unCommdLineMatch.group('nestedComInds', 'nonCom', 'wholeCom')
    else:
        nestedComInds, nonCom, wholeCom = "", "", ""
    F_commented = bool(commdLineMatch)
    tagOptionSettingMatches = tagOptionSettingRe.findall(wholeCom)

    logging.debug(f"LINE[{lineNum}](L{fDb.nestedLvl:1},"
                  f"{str(fDb.F_multiLineActive)[0]})"
                  f"({fDb.comInd},{str(F_commented)[0]}):{line[:-1]}")

    # Parse commented part of line; determine inline matches
    inlineOptionCount = defaultdict(lambda: 0)
    inlineOptionMatch = defaultdict(lambda: False)
    inlineSettingMatch = defaultdict(lambda: False)
    F_inlineOptionMatch = False
    for mtag, tag, rawOpt, setting in tagOptionSettingMatches:
        # Build database of related file locations
        if inp.F_showfiles:
            showFilesDb[tag+rawOpt][str(fDb.filePath)] = True
        # Count occurances of rawOpt
        inlineOptionCount[tag+rawOpt] += 1
        if (inp.tag+inp.rawOpt).replace('\\', '') == tag+rawOpt:
            inlineOptionMatch[tag+rawOpt] = True
            F_inlineOptionMatch = True
            if inp.setting.replace('\\', '') == setting:
                inlineSettingMatch[tag+rawOpt] = True

    # Multi-line option logic:
    # Toggle (comment or uncomment) line if multi-line option is active
    if fDb.F_multiLineActive and not F_inlineOptionMatch:
        if fDb.F_multiCommented:
            newLine = _uncomment(line, fDb.comInd, lineNum)
        else:
            newLine = _comment(line, fDb.comInd, lineNum)
        F_freezeChanges = True
    else:
        F_freezeChanges = False

    # All other required logic based on matches in line
    for mtag, tag, rawOpt, setting in tagOptionSettingMatches:
        logging.debug(f"\tMATCH(freeze={str(F_freezeChanges)[0]}):"
                      f"{mtag}{tag}{rawOpt} {setting}")
        # Skip rest of logic if change-freeze is set
        if F_freezeChanges:
            continue

        # Logic for determining levels for nested options
        if mtag:  # multitag present in line
            if F_commented:
                fDb.nestedOptionDb[fDb.nestedLvl] = tag+rawOpt
                fDb.nestedIncrement = 1
            else:  # uncommented
                logging.debug(fDb.nestedOptionDb)
                if len(fDb.nestedOptionDb) < 1:
                    pass
                elif fDb.nestedOptionDb[fDb.nestedLvl-1] == tag+rawOpt:
                    logging.debug("nested uncommented match")
                    fDb.nestedOptionDb.pop(fDb.nestedLvl-1)
                    fDb.nestedIncrement = -1
                    F_commented = True
                    fDb.F_multiLineActive = False
                    F_freezeChanges = True
                    if inlineSettingMatch[tag+rawOpt]:  # match input setting
                        newLine = _uncomment(line, fDb.comInd, lineNum)
                    continue
        else:  # no multitag present
            pass

        # Build database of available options and settings
        if inp.F_available or inp.F_bashComp:
            # Determine active, inactive, and simultaneous options
            if re.search(ANY_VAR_SETTING, setting) and not F_commented:
                strToReplace = _parse_inline_regex(nonCom, setting, varErrMsg)
                varOptionsValuesDb[tag+rawOpt][strToReplace] = '='
            elif optionsSettingsDb[tag+rawOpt][setting] is None:
                if inlineOptionCount[tag+rawOpt] > 1:
                    optionsSettingsDb[tag+rawOpt][setting] = None
                else:
                    optionsSettingsDb[tag+rawOpt][setting] = (not F_commented)
            elif optionsSettingsDb[tag+rawOpt][setting] != (not F_commented):
                optionsSettingsDb[tag+rawOpt][setting] = '?'  # ambiguous
            else:
                pass

        # Modify line based on user input and regular expression matches
        if not inp.F_available:
            # Match input option (tag+rawOpt)
            if ((inp.tag+inp.rawOpt).replace('\\', '') == tag+rawOpt):
                if F_commented:  # commented line
                    if (inp.setting == setting):  # match input setting
                        # Uncomment lines with input tag+rawOpt and setting
                        newLine = _uncomment(line, fDb.comInd, lineNum)
                        if mtag and not fDb.F_multiLineActive:
                            fDb.F_multiLineActive = True
                            fDb.F_multiCommented = F_commented
                        elif mtag and fDb.F_multiLineActive:
                            fDb.F_multiLineActive = False
                            fDb.F_multiCommented = None
                    else:  # setting does not match
                        pass
                else:  # uncommented line
                    # If variable option, use input regex to modify line
                    if re.search(ANY_VAR_SETTING, setting):
                        strToReplace = _parse_inline_regex(nonCom, setting,
                                                           varErrMsg)
                        replaceStr = inp.setting
                        if replaceStr == strToReplace:
                            logging.info(f"Option already set: {replaceStr}")
                        else:
                            with _handle_errors(errTypes=AttributeError,
                                                msg=varErrMsg):
                                newLine = _set_var_option(
                                    line, fDb.comInd, lineNum, replaceStr,
                                    setting, nestedComInds, nonCom, wholeCom)
                                F_freezeChanges = True
                    # Not 1 match in line
                    elif (inlineOptionMatch[tag+rawOpt]) and\
                            (not inlineSettingMatch[tag+rawOpt]):
                        newLine = _comment(line, fDb.comInd, lineNum)
                        if mtag and not fDb.F_multiLineActive:
                            fDb.F_multiLineActive = True
                            fDb.F_multiCommented = F_commented
                            F_freezeChanges = True
                        elif mtag and fDb.F_multiLineActive:
                            fDb.F_multiLineActive = False
                            fDb.F_multiCommented = None
                            F_freezeChanges = True
                        else:
                            pass
                    else:
                        pass
            else:
                pass
        else:
            pass

    if not newLine == line:  # if 1 line in file is change, file is modified
        fDb.F_fileModified = True

    return newLine


def _process_file(filePath, inputDb, optionsSettingsDb, varOptionsValuesDb,
                  showFilesDb):
    """Process individual file.
    Update optionsSettingsDb and varOptionsValuesDb
    Return if changes have been made or not

    General algorithm is to scroll through file line by line, applying
    consistent logic to make build database of available options or to make the
    desired changes.
    """
    logging.debug(f"FILE CANDIDATE: {filePath}")

    # Check file size and line count of file
    lineCount = _line_count(filePath, lineLimit=inputDb.maxFileLines)
    fsizeKb = filePath.stat().st_size/1000
    if fsizeKb > inputDb.maxFileSizeKb:
        reasonStr = f"File exceeds kB size limit of {inputDb.maxFileSizeKb}"
        _skip_file_warning(filePath,
                           reason=reasonStr)
        return False
    elif lineCount > inputDb.maxFileLines:
        reasonStr = f"File exceeds line limit of {inputDb.maxFileLines}"
        _skip_file_warning(filePath,
                           reason=reasonStr)
        return False

    # Instantiate and initialize file variables
    fDb = FileVarsDatabase(filePath, inputDb)

    # Only continue if a comment index is found in the file
    if not fDb.comInd:
        return False
    logging.debug(f"FILE MATCHED [{fDb.comInd}]: {filePath}")

    # Read file and parse options in comments
    with open(filePath, 'r', encoding='UTF-8') as file:
        newLines = ['']*lineCount
        for idx, line in enumerate(_yield_utf8(file)):
            lineNum = idx + 1
            newLines[idx] = _process_line(line, lineNum, fDb,
                                          optionsSettingsDb,
                                          varOptionsValuesDb, showFilesDb)

    # Write file
    if fDb.F_fileModified:
        with open(filePath, 'w', encoding='UTF-8') as file:
            file.writelines(newLines)
        _print_and_log(f"File modified: {file.name}")
        return True
    else:
        return False


def _scroll_through_files(validFiles, inputDb):
    """Scroll through files, line by line. This function:
    * This is heart of the code. """
    inp = inputDb
    optionsSettingsDb = defaultdict(lambda: defaultdict(lambda: None))
    varOptionsValuesDb = defaultdict(lambda: defaultdict(lambda: None))
    if inp.F_showfiles:
        showFilesDb = defaultdict(lambda: defaultdict(lambda: None))
    else:
        showFilesDb = None
    F_changesMade = False

    if inp.F_available:
        logging.info("Scrolling through files to gather available options")
    else:
        logging.info(("Scrolling through files to set: {inp.tag}{inp.rawOpt} "
                      "{inp.setting}").format(inp=inputDb))

    for filePath in validFiles:
        F_fileChanged = _process_file(filePath, inputDb, optionsSettingsDb,
                                      varOptionsValuesDb, showFilesDb)
        if F_fileChanged:
            F_changesMade = True

    # Cut out options with a singular setting. Could try filter() here
    optionsSettingsDb = {
        tg: n for tg, n in optionsSettingsDb.items() if len(n) > 1}

    return optionsSettingsDb, varOptionsValuesDb, showFilesDb, F_changesMade


def _fn_compare(globSet, compareArray):
    """Compare set with unix * expressions with array of files or directories.
    """
    for g in globSet:
        for c in compareArray:
            if fnmatch(c, g):
                return True
    else:  # no break
        return False


def _gen_valid_files(ignoreFiles, ignoreDirs):
    """Generator to get non-ignored files in non-ignored directories. """
    for dirPath, _, files in os.walk('.', followlinks=True):
        if not _fn_compare(ignoreDirs, dirPath.split(os.sep)):
            for file in files:
                if not _fn_compare(ignoreFiles, (file,)):
                    #print("DEBUG NOT IGNORED:", file)
                    yield Path(f"{dirPath}/{file}")


def _str_dict(dict_):
    """Return dictionary with string representation of arrays (no brackets).
    """
    return {k: str(v).lstrip('[').rstrip(']') for k, v in dict_.items()}


def _array_from_str(arrayStr):
    """Return an array from a string of an array. """
    return [a.replace("'", '').replace('"', '').strip()
            for a in arrayStr.split(',')]


def _load_program_settings(args):
    """Load program settings if file provided by user, else use default. """
    configFile = Path(args.auxDir) / f"{BASENAME_NO_EXT}.cfg"
    config = {'ignoreDirs': IGNORE_DIRS,
              'ignoreFiles': IGNORE_FILES,
              'maxFileLines': MAX_FLINES,
              'maxFileSizeKb': MAX_FSIZE_KB, }
    cfg = ConfigParser()
    cfg.optionxform = str  # maintain case even on Windows
    section = 'Files'
    if Path.exists(configFile):
        logging.info(f"Reading program settings from {configFile}:")
        cfg.read(configFile)
        config['maxFileLines'] = int(cfg[section].get('maxFileLines'))
        config['maxFileSizeKb'] = int(cfg[section].get('maxFileSizeKb'))
        config['ignoreDirs'] = _array_from_str(
                cfg[section].get('ignoreDirs'))
        config['ignoreFiles'] = _array_from_str(
                cfg[section].get('ignoreFiles'))
    else:
        if args.bashCompletion or not args.noLog:  # only write when allowed to
            logging.info("Using default program settings:")
            cfg[section] = _str_dict(config)
            #_write_config_file(configFile, config)
            with open(configFile, 'w') as file:
                cfg.write(file)
    logging.info(config)
        
    return config


def _parse_and_check_input(args, config):
    """Parse input arguments. """
    InputDb = namedtuple('InputDb', ['tag', 'rawOpt', 'setting',
                                         'F_available', 'F_bashComp',
                                         'F_showfiles', 'maxFileLines',
                                         'maxFileSizeKb', ])

    if args.setting == '' or args.showFiles:
        args.available = True

    if args.available:
        return InputDb(tag=ANY_TAG, rawOpt=ANY_RAW_OPTION,
                         setting=args.setting, F_available=args.available,
                         F_bashComp=args.bashCompletion,
                         F_showfiles=args.showFiles,
                         maxFileLines=config['maxFileLines'],
                         maxFileSizeKb=config['maxFileSizeKb'])
    else:
        # Check if setting is formatted correctly
        with _handle_errors(errTypes=AttributeError,
                            msg=INVALID_SETTING_MSG):
            setting = re.search(f"(^{VALID_INPUT_SETTING}$)",
                                args.setting).group(0)
        # Check if option is formatted correctly
        checkTagOptionRe = re.compile(
                "^({mtag}*)({tag}+)({rawOpt})$".format(**GENERIC_RE_VARS))
        with _handle_errors(errTypes=(AttributeError),
                            msg=INVALID_OPTION_MSG):
            mtag, tag, rawOpt = checkTagOptionRe.search(args.option).groups()
        literalTag = ''.join([rf'\{s}' for s in tag])  # read as literal
        return InputDb(tag=literalTag, rawOpt=rawOpt, setting=setting,
                         F_available=args.available,
                         F_bashComp=args.bashCompletion, F_showfiles=False,
                         maxFileLines=config['maxFileLines'],
                         maxFileSizeKb=config['maxFileSizeKb'])


def optionset(argsArr):
    """Main optionset function. Input array of string arguments. """
    startTime = time()  # time program

    # Parse arguments
    args = parser.parse_args(argsArr)
    if args.helpFull:
        parser.description = FULL_HELP_DESCRIPTION
        parser.print_help()
        return True
    elif args.version:
        print(f"{BASENAME} {__version__}")
        return True


    global F_QUIET, F_VERBOSE
    F_QUIET = args.quiet
    F_VERBOSE = args.verbose

    # Set up logging
    args.auxDir = Path(args.auxDir)
    logLevel = 'DEBUG' if args.debug else 'INFO'
    if args.noLog:
        logPath = Path(os.devnull)
    else:
        args.auxDir.mkdir(parents=True, exist_ok=True)
        logPath = args.auxDir / LOG_NAME
        if Path.exists(logPath):  # use unlink(missing_ok=True) if Python 3.8
            logPath.unlink()
    logFormat = "%(levelname)s:%(message)s"
    logging.basicConfig(filename=logPath, level=logLevel, format=logFormat)

    # Run algorithm
    logging.info("Executing main optionset function")

    logging.info("Checking input options")
    logging.debug(f"args = {args}")
    config = _load_program_settings(args)
    inputDb = _parse_and_check_input(args, config)
    logging.info(f"<tag><rawOpt> <setting> = "
                 f"{inputDb.tag}{inputDb.rawOpt} {inputDb.setting}")

    logging.info("Generating valid files")
    validFiles = list(_gen_valid_files(config['ignoreFiles'],
                                       config['ignoreDirs']))
    logging.info(f"Valid files: {[str(vf) for vf in validFiles]}")

    optionsSettingsDb, varOptionsValuesDb, showFilesDb, F_changesMade = \
        _scroll_through_files(validFiles, inputDb=inputDb)

    if args.available:
        globPat = '*' if args.option is None else f"{args.option}*"
        _print_available(optionsSettingsDb, varOptionsValuesDb, showFilesDb,
                         globPat)

    if args.bashCompletion:
        _write_bash_completion_file(optionsSettingsDb, varOptionsValuesDb,
                                   bashCompPath=args.auxDir/BASHCOMP_NAME)

    if F_changesMade and F_VERBOSE:
        _print_and_log(f"See all modifications in {logPath}")

    logging.info(f"Finished in {(time()-startTime):1.5f} s")

    return True


def main():
    """Main function. """
    argsArr = argv[1:] if len(argv) > 1 else [""]
    optionset(argsArr)


# ############################################################ #
# Run main optionset function
# ############################################################ #
if __name__ == '__main__':
    main()
