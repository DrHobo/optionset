#!/usr/bin/env python3
"""
Enable/disable user-predefined options in text-based dictionaries.
Use -h to view help.

Author: Matthew Jones
Email: weehikematt@yahoo.com
"""

## Import files
import argparse
import logging
import os
import re
#import pdb; pdb.set_trace()
from collections import defaultdict, namedtuple, OrderedDict # , deque
from contextlib import contextmanager
from fnmatch import fnmatch
from functools import wraps
from pprint import pformat
from sys import exit
from time import time

## Time program
START_TIME = time()

## Set up input argument parser
BASENAME = os.path.basename(__file__)
DESCRIPTION = f"""
This program enables and disables user-predefined options in text-based code
and dictionary files in the base directory and below.  The user specifies the
lines in the files that will either be enabled or disabled by adding macro
commands as commented text.  For example, the OpenFOAM dictionary text file
'system/controlDict' could be written as,

application pimpleFoam // @simulation transient
//application simpleFoam // @simulation steady

This setup allows the user to easily switch between transient and steady
simulations without manually editting the file.  Simply run,

{BASENAME} @simulation steady

and the dictionary file will be modified and re-written as,

//application pimpleFoam // @simulation transient
application simpleFoam // @simulation steady

where the steady solver 'simpleFoam' is now uncommented and active. Here
@simulation is the 'option' while transient and steady are the 'settings'.  
An unlimited number of unique options and settings are allowed.  Each can only
be composed of alphanumerical words with dots, pluses, minuses, and underscores.  
Note that the first one or more characters in a option must be a special symbol 
(non-bracket, non-comment-indicator, non-option/setting) such as '~`!@$%^&|\\?'.

Use '{BASENAME} -a ' to view all of the options that you have set, or even 
'{BASENAME} -a @simple' to view all options that begin with '@simple'.

To avoid comment clutter, multi-line options are encouraged by writing * in
front of the first and last options in a series (see text on left),

functions        // *@forces on    | <---  |   functions        // @forces on
{{                                  |INSTEAD|   {{                // @forces on
#include "forces"                  |  OF   |   #include "forces"// @forces on
}}                // *@forces on    | --->  |   }}                // @forces on
//               // @forces off    |       |   //               // @forces off

An additional feature is a variable option.  For variable options the dictionary
text file must be formatted with a Perl-styled regular expression ='<regex>' 
that matches the desired text to be changed such as,

variable option = 5.5; // @varOption ='= (.*);'

To change 'variable option' to 6.7 use, '{BASENAME} @varOption 6.7'. The file becomes,

variable option = 6.7; // @varOption ='= (.*);'

Using your favorite scripting language, it is convenient to glue this program 
into more advanced option variation routines to create advanced parameter
sweeps and case studies.
"""
        
parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=DESCRIPTION)
parser.add_argument(
        'option', metavar='option', nargs='?', type=str, default="",
        help='\'option\' name')
parser.add_argument(
        'setting', metavar='setting', nargs='?', type=str, default="",
        help='\'setting\' for given \'option\'')
parser.add_argument(
        '-a', '--available', dest='available', default=False, action='store_true',
        help=('show available option-setting combinations. '
            'Allows for unix-style regular expression searching'))
parser.add_argument(
        '-v', '--verbose', dest='verbose', default=False, action='store_true',
        help='turn on verbose output')
parser.add_argument(
        '-q', '--quiet', dest='quiet', default=False, action='store_true',
        help='turn off all standard output')
parser.add_argument(
        '-d', '--debug', dest='debug', default=False, action='store_true',
        help='turn on debug output in log file')
args = parser.parse_args()

## Set up logging
RUNCMD = BASENAME
LOG_PATH = f'.log.{BASENAME}'
LOG_LEVEL = 'DEBUG' if args.debug else 'INFO'
if os.path.exists(LOG_PATH):
    os.remove(LOG_PATH)
logging.basicConfig(filename=LOG_PATH, level=LOG_LEVEL)

## Initialize global variables
IGNORE_DIRS = {'processor[0-9]*', '.git', '[0-9]', '[0-9][0-9]*', '[0-9].[0-9]*', 
        'triSurface', 'archive', 'sets', 'log', 'logs'}  # UNIX-based wild cards
IGNORE_FILES = {BASENAME, LOG_PATH, '.*', 'log.*', '*.log', '*.py', 
        '*.gz', 'faces', 'neighbour', 'owner', 'points*', 'buildTestMatrix', 
        '*.png', '*.jpg', '*.obj', '*.stl', '*.stp', '*.step', }
MAX_FLINES = 9999  # maximum lines per file
MAX_FSIZE_KB = 10  # maximum file size, kilobytes

# Regular expression frameworks
ANY_COMMENT_IND = r'(?:[#%!]|//|--)'  # comment indicators: # % // -- !
MULTI_TAG = r'[*]'  # for multi-line commenting
ANY_WORD = r'[\+a-zA-Z0-9._-]+'
ANY_OPTION = ANY_WORD
ANY_VAR_SETTING = r'\={quote}.+{quote}'.format(quote=r'[\'"]')
ANY_SETTING = r'(?:{anyWord}|{anyVar})'.format(anyWord=ANY_WORD, anyVar=ANY_VAR_SETTING)
VALID_INPUT_SETTING = '(?: |{})+'.format(ANY_WORD)  # words with spaces (using '')
BRACKETS = r'[()<>\[\]]'
ANY_TAG = f'(?:(?!\s|{ANY_COMMENT_IND}|{MULTI_TAG}|{ANY_WORD}|{BRACKETS}).)'  # not these; implicitely set
#ANY_TAG = r'[~`!@$^&\\\?\|]'  # explicitely set
WHOLE_COMMENT = (r'(?P<comInd>{comInd})'
    r'(?P<wholeCom>.*\s+{mtag}*{tag}+{option}\s+{setting}\s.*\n?)')
#UNCOMMENTED_LINE = r'(?P<nonCom>^\s*(?:(?!{comInd}).)+)' + WHOLE_COMMENT
#COMMENTED_LINE = r'(?P<nonCom>^\s*{comInd}(?:(?!{comInd}).)+)' + WHOLE_COMMENT
UNCOMMENTED_LINE = r'^{nestedComInds}(?P<nonCom>\s*(?:(?!{comInd}).)+)' + WHOLE_COMMENT
COMMENTED_LINE = r'^{nestedComInds}(?P<nonCom>\s*{comInd}(?:(?!{comInd}).)+)' + WHOLE_COMMENT
ONLY_TAG_GROUP_SETTING = r'({mtag}*)({tag}+)({option})\s+({setting})\s'
GENERIC_RE_VARS = {'comInd':ANY_COMMENT_IND, 'mtag':MULTI_TAG, 'tag':ANY_TAG,
        'option':ANY_OPTION, 'setting':ANY_SETTING, 'nestedComInds':''}

# Error messages
INCOMPLETE_INPUT_MSG = f'''InputError:
Incomplete input. Try:
    "{RUNCMD} -h"                    to view help
    "{RUNCMD} -a"                    to view available options
    "{RUNCMD} -a <unix regex>"       to search options using a unix regex
    "{RUNCMD} <option> <setting>"    to set the <setting> of <option>'''
INVALID_OPTION_MSG = f'''InputError:
Invalid option name. A preceding tag, such as '@' in '@option' is required, and
the rest of the option must adhere to the following regular expression: {ANY_WORD}
To view help try:
    "{RUNCMD} -h"'''
INVALID_SETTING_MSG = f'''InputError:
Invalid setting name. The setting name must adhere to the following regular 
expression: {ANY_WORD}
To view help try:
    "{RUNCMD} -h"'''
INVALID_VAR_REGEX_MSG = '''FormatError:
Invalid 'variable setting' regular expression. The commented regular expression 
must adhere to this form: %(anyVar)s
(e.i. an equals sign followed by a user specified regular expression in quotes)
Additionally, the corresponding code on the line of this 'variable setting' must
match the user specified regular expression in quotes. This regular expression
must have one and only one set of parentheses surrounding the variable option to
be matched such as '(.*)'.  Otherwise, To specify literal parentheses in the 
regex, use '\('.
\r\nFile:{fileName}
Line {lineNum}:{line}
To view help try:
    "%(runCmd)s -h"''' % {'anyVar':ANY_VAR_SETTING, 'runCmd':RUNCMD}
PRINT_AVAIL_DEF_HDR_MSG = '''Printing available options and settings,
('  inactive  ', '> active <', '? both ?', '= variable ='):'''
INVALID_REGEX_GROUP_MSG = '''InvalidRegexGroupError: {specificProblem}.
A regular expression 'group' is denoted by a surrounding pair of parentheses '()'
The commented variable setting should be the only group.'
Use '()' to surround only the variable setting group in the commented regular expression.'''

## Define classes
class FileFlags:
    """Stores flags for line-by-line commenting features. """
    def __init__(self, F_fileModified=False, F_commented=None,
            F_multiLineActive=False, F_multiCommented=None,
            F_freezeChanges=False, nestedLvl=0):
        """Initialize flags. """
        self.F_fileModified = F_fileModified
        self.F_commented = F_commented
        self.F_multiLineActive = F_multiLineActive
        self.F_multiCommented = F_multiCommented
        self.F_freezeChanges = F_freezeChanges
        self.nestedLvl = nestedLvl
        
## Define utility functions
def print_available(db, globPat='*', headerMsg=PRINT_AVAIL_DEF_HDR_MSG):
    """Print available options and options for use; optionally sort with unix regex. """
    if headerMsg:
        print_and_log(headerMsg)
    logging.info(pformat(db, indent=1))
    for item in sorted(db.items()):
        if not fnmatch(item[0], globPat):
            continue
        print_and_log(f"  {item[0]}")
        for subItem in sorted(item[1].items()):
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
            print_and_log(f"\t{leftStr} {subItem[0]} {rightStr}")

def multi_line_logic(mtag, fFlags):
    """Set multi-line flags based on current conditions. """
    if mtag and not fFlags.F_multiLineActive:
        fFlags.F_multiLineActive = True
        fFlags.F_multiCommented = fFlags.F_commented
    elif mtag and fFlags.F_multiLineActive:
        fFlags.F_multiLineActive = False
        fFlags.F_multiCommented = None
    return fFlags

def log_before_after_commenting(func):
    """Wrapper to add file modifications to the log file. """
    @wraps(func)
    def log(*args_, **kwargs):
        lineBeforeMod = '[{:>4} ]{}'.format(args_[2], args_[0].rstrip('\r\n'))
        returnStr = func(*args_, **kwargs)
        lineAfterMod = '[{:>4}\']{}'.format(args_[2], returnStr.rstrip('\r\n'))
        if args.verbose:
            print_and_log(lineBeforeMod)
            print_and_log(lineAfterMod)
        else:
            logging.info(lineBeforeMod)
            logging.info(lineAfterMod)
        return returnStr
    return log

@log_before_after_commenting
def un_comment(line, comInd, lineNum):
    """Uncomment a line. Input requires comment indicator string. """
    line = re.sub(f'^\s*({comInd})', "", line)
    return line

@log_before_after_commenting
def comment(line, comInd, lineNum):
    """Comment a line. Input requires comment indicator string. """
    line = comInd + line
    return line

def check_varop_groups(reStr):
    """Calculate the number of regex groups designated by (). """
    allGroups = re.findall(r'([^\\]\(.*?[^\\]\))', reStr)
    if allGroups is None:
        print_and_log(INVALID_REGEX_GROUP_MSG.format(
            specificProblem='No regex groups found.\r\n'))
        raise AttributeError
    elif len(allGroups) > 1:
        print_and_log(INVALID_REGEX_GROUP_MSG.format(
            specificProblem='More than one regex group \'()\' found'))
        raise AttributeError
    else:
        return len(allGroups)

def add_left_right_groups(inLineRe):
    """Add left and right groups to regex.
    For example: \( (.*) 0 0 \) >>>> (\( )(.*)( 0 0 \)) """
    parensRe = (r'[^\\]([\(])', r'[^\\]([\)])')
    # Must add one to get rid of preceding character match
    leftParenInd = re.search(r'[^\\]([\(])', inLineRe).start() + 1
    rightParenInd = re.search(r'[^\\]([\)])', inLineRe).start() + 1
    left = inLineRe[:leftParenInd]
    mid = inLineRe[leftParenInd:rightParenInd + 1]
    right = inLineRe[rightParenInd + 1:]
    newInLineRe = f"({left}){mid}({right})"
    return newInLineRe

@log_before_after_commenting
def set_var_option(line, comInd, lineNum, replaceStr, setting, strToReplace,
        nonCom, wholeCom):
    """Return line with new variable option set. """
    # First ensure that there is only one () in the re
    #inLineReSearch = re.search(inLineRe, nonCom)
    # Next, add 2 new groups, one for the left side and the other for the right
    inLineRe = in_line_regex(setting)
    logging.info(f"Setting variable option:{inLineRe}:{replaceStr}")
    newInLineRe = add_left_right_groups(inLineRe)

    def replace_F(m):
        return m.group(1) + replaceStr + m.group(3)
    newNonCom = re.sub(newInLineRe, replace_F, nonCom)
    return newNonCom + comInd + wholeCom

def skip_file_warning(fileName, reason):
    """Log a warning that the current file is being skipped. """
    logging.warning(f"Skipping: {fileName}")
    logging.warning(f"Reason: {reason}")

def yield_utf8(file):
    """Yield file lines only if they are utf-8 encoded (non-binary). """
    try:
        for line in file:
            yield line
    except UnicodeDecodeError as err:
        skip_file_warning(file.name, err)

def line_count(fileName, lineLimit):
    """Return number of lines in a file unless file exceeds line limit. """
    lineCount = 0
    with open(fileName, 'r') as file:
        for line in yield_utf8(file):
            lineCount += 1
            if lineCount > lineLimit:
                return lineCount + 1  # return line limit +1 if line-count exheeds
    return lineCount

def get_comment_indicator(fileName):
    """Get comment indicator from fileName ('#', '//', or' %'). """
    with open(fileName, 'r') as file:
        comLineRe = re.compile(f'^\s*({ANY_COMMENT_IND}).*')
        for line in yield_utf8(file):
            searchComLine = comLineRe.search(line)
            if searchComLine:
                return searchComLine.group(1)

        logging.debug('Comment not found at start of line. Searching in-line.')
        unComLineRe = re.compile(UNCOMMENTED_LINE.format(**GENERIC_RE_VARS))
        file.seek(0)  # restart file
        for line in yield_utf8(file):
            searchUnComLine = unComLineRe.search(line)
            if searchUnComLine:
                return searchUnComLine.group('comInd')

def in_line_regex(settingStr):
    """Return in-line regular expression using setting."""
    return settingStr[2:-1]  # remove surrounding =''


def parse_inline_regex(nonCommentedText, setting, varErrMsg=""):
    """Parse variable option value using user-defined regular expression
    stored in 'setting'.
    """
    # Attribute handles regex fail. Index handles .group() fail
    #TODO 2015-08-16: handle sre_constants.error for unbalanced parentheses
    with handle_errors(errTypes=(AttributeError, IndexError), msg=varErrMsg):
        inLineRe = in_line_regex(setting)
        check_varop_groups(inLineRe)
        strToReplace = re.search(inLineRe, nonCommentedText).group(1)
    return strToReplace


def build_regexes(regexVars):
    """Build regular expressiones for commented line, uncommented lin and
    tag+option+setting.
    """
    comLineRe = re.compile(COMMENTED_LINE.format(**regexVars))
    unComLineRe = re.compile(UNCOMMENTED_LINE.format(**regexVars))
    tagOptionSettingRe = re.compile(ONLY_TAG_GROUP_SETTING.format(**regexVars))
    return comLineRe, unComLineRe, tagOptionSettingRe


def process_file(validFile, userInput, F_getAvailable, allOptionsSettings,
        allVariableOptions):
    """Process individual file. 
    Update allOptionsSettings and allVariableOptions
    Return if changes have been made or not

    General algorithm is to scroll through file line by line, applying
    consistent logic to make build database of available options or to make the
    desired changes.
    """
    logging.debug(f"FILE CANDIDATE: {validFile}")

    # Check file size and line count of file
    lineCount = line_count(validFile, lineLimit=MAX_FLINES)
    fsizeKb = os.stat(validFile).st_size/1000
    if fsizeKb > MAX_FSIZE_KB:
        skip_file_warning(validFile,
                reason=f"File exceeds kB size limit of {MAX_FSIZE_KB}")
        return False
    elif lineCount > MAX_FLINES: 
        skip_file_warning(validFile,
                reason=f"File exceeds line limit of {MAX_FLINES}")
        return False
    
    # Get string that signifies a commented line
    comInd = get_comment_indicator(validFile)
    if not comInd:
        return False
    logging.debug(f"FILE MATCHED [{comInd}]: {validFile}")

    # IMPL 2020-09-01: use generic options and settings first to establish nested then specifics
    #       - Use ANY_OPTION ANY_SETTING
    # Prepare regular expressions
    nestedOptionDb = OrderedDict()
    genericReVars = GENERIC_RE_VARS
    genericReVars['comInd'] = comInd
    inputReVars = {'comInd':comInd, 'mtag':MULTI_TAG, 'tag':userInput.tag,
            'option':userInput.option, 'setting':ANY_SETTING, 'nestedComInds':''}


    # Read file and parse options in comments
    with open(validFile, 'r') as file: 
        fFlags = FileFlags()
        newLines = ['']*lineCount
        nestedIncrement = 0
        for idx, line in enumerate(yield_utf8(file)):
            newLines[idx] = line
            lineNum = idx + 1
            fFlags.nestedLvl += nestedIncrement
            nestedIncrement = 0 # reset
            #print(f"\nDEBUG_{fFlags.nestedLvl:2}_{line[:-1]}")
            genericReVars['nestedComInds'] = f"\s*{comInd}"*fFlags.nestedLvl
            inputReVars['nestedComInds'] = f"\s*{comInd}"*fFlags.nestedLvl
            #comLineRe, unComLineRe, tagOptionSettingRe = build_regexes(inputReVars) @old
            genericComLineRe, genericUnComLineRe, genericTagOptionSettingRe = build_regexes(genericReVars)
            inputComLineRe, inputUnComLineRe, inputTagOptionSettingRe = build_regexes(inputReVars)
            genricComMatch = genericComLineRe.search(line)
            genericUnComMatch = genericUnComLineRe.search(line)

            #print("\t\tmlineactive:", fFlags.F_multiLineActive, fFlags.F_multiCommented)
            # Get whole commented part of line
            wholeCom = ''
            fFlags.F_commented = None
            if genricComMatch:  # must search for commented before uncommented
                nonCom, wholeCom = genricComMatch.group('nonCom', 'wholeCom')
                fFlags.F_commented = True
                #print("BINGA")
            elif genericUnComMatch:
                nonCom, wholeCom = genericUnComMatch.group('nonCom', 'wholeCom')
                fFlags.F_commented = False
                #print("ZINGA")

            # Parse commented part of line
            varErrMsg = INVALID_VAR_REGEX_MSG.format(fileName=validFile,
                    lineNum=lineNum, line=line)
            tagOptionSettingMatches = genericTagOptionSettingRe.findall(wholeCom)
            #NMatches = len(tagOptionSettingMatches)
            #for reMatch in genericTagOptionSettingRe.finditer(wholeCom):
                #mtag, tag, option, setting = reMatch.groups()
            inlineOptionCount = defaultdict(lambda: 0)
            inlineOptionMatch = defaultdict(lambda: False)
            inlineSettingMatch = defaultdict(lambda: False)
            inlineMTagMatch = defaultdict(lambda: False)
            F_optionSettingMatch = False
            for mtag, tag, option, setting in tagOptionSettingMatches:
                inlineOptionCount[tag+option] += 1  # count occurances of option
                if re.search(userInput.tag+userInput.option, tag+option):
                    inlineOptionMatch[tag+option] = True
                    if re.search(userInput.setting, setting):
                        inlineSettingMatch[tag+option] = True
                        F_optionSettingMatch = True
                if mtag:
                    inlineMTagMatch[tag+option] = True

            if fFlags.F_multiLineActive and not F_optionSettingMatch: # 2020-09-02: add logic to make sure options right
                #print("ZOOOO")
                lineNum = idx+1
                if fFlags.F_multiCommented:
                    #print("\t ABA")
                    newLine = un_comment(line, comInd, lineNum)
                else:
                    #print("\t ZABA")
                    newLine = comment(line, comInd, lineNum)
                newLines[idx] = newLine  # redundant
                fFlags.F_fileModified = True
                continue

            fFlags.F_freezeChanges = False
            for mtag, tag, option, setting in tagOptionSettingMatches:
                if fFlags.F_freezeChanges:
                    continue
                logging.debug((f"\tMATCH com({fFlags.F_commented}) "
                        "[{idx}]:{comInd}:{tag}:{option}:{setting}"))
                # Logic for determining levels for nested options
                if mtag:
                    if fFlags.F_commented:
                        nestedOptionDb[fFlags.nestedLvl] = tag+option
                        nestedIncrement = 1
                    else: # uncommented
                        if len(nestedOptionDb) < 1:
                            pass
                        elif nestedOptionDb[fFlags.nestedLvl-1] == tag+option:
                            nestedOptionDb.pop(fFlags.nestedLvl-1)
                            nestedIncrement = -1
                            fFlags.F_commented = True
                if F_getAvailable:  # build database of available options
                    # Determine active, inactive, and simultaneous options
                    if re.search(ANY_VAR_SETTING, setting) and not fFlags.F_commented: 
                        strToReplace = parse_inline_regex(nonCom, setting, varErrMsg)
                        allVariableOptions[tag+option][strToReplace] = '='
                    elif allOptionsSettings[tag+option][setting] is None:
                        if inlineOptionCount[tag+option] > 1:
                            allOptionsSettings[tag+option][setting] = None
                        else:
                            allOptionsSettings[tag+option][setting] = (not fFlags.F_commented)
                    elif allOptionsSettings[tag+option][setting] != (not fFlags.F_commented):
                        allOptionsSettings[tag+option][setting] = '?'  # ambiguous
                else: # modify line based on user input
                    if re.search(userInput.tag+userInput.option, tag+option): # match input tag+option
                        if fFlags.F_commented:  # commented line
                            if re.search(userInput.setting, setting): # match input setting
                                # Uncomment lines with input tag+option and with input setting
                                newLines[idx] = un_comment(line, comInd, lineNum)
                                fFlags.F_fileModified = True
                                fFlags = multi_line_logic(mtag, fFlags)
                        else: # uncommented line
                            if re.search(ANY_VAR_SETTING, setting):
                                print("ZABAZAB")
                                # If variable option, use user-supplied regex to modify line
                                strToReplace = parse_inline_regex(nonCom, setting, varErrMsg)
                                replaceStr = userInput.setting
                                if replaceStr == strToReplace:
                                    logging.info(f"Option already set: {replaceStr}")
                                    print("BAAA")
                                else:
                                    print("CAAA")
                                    with handle_errors(errTypes=AttributeError, msg=varErrMsg):
                                        print("DAAA")
                                        newLines[idx] = set_var_option(line, comInd, lineNum,
                                                replaceStr, setting, strToReplace, nonCom, wholeCom)
                                    print("EAAA")
                                    fFlags.F_fileModified = True
                                    fFlags.F_freezeChanges = True
                                continue

                        #if re.search(ANY_VAR_SETTING, setting) and not fFlags.F_commented:
                        #    print("ZABAZAB")
                        #    # If variable option, use user-supplied regex to modify line
                        #    strToReplace = parse_inline_regex(nonCom, setting, varErrMsg)
                        #    replaceStr = userInput.setting
                        #    if replaceStr == strToReplace:
                        #        logging.info(f"Option already set: {replaceStr}")
                        #        print("BAAA")
                        #    else:
                        #        print("CAAA")
                        #        with handle_errors(errTypes=AttributeError, msg=varErrMsg):
                        #            print("DAAA")
                        #            newLines[idx] = set_var_option(line, comInd, lineNum,
                        #                    replaceStr, setting, strToReplace, nonCom, wholeCom)
                        #        print("EAAA")
                        #        fFlags.F_fileModified = True
                        #        fFlags.F_freezeChanges = True
                        #        continue
                        #else:
                        #    pass

                        #if re.search(userInput.setting, setting): # match input setting
                        #    if fFlags.F_commented:  # commented line
                        #        # Uncomment lines with input tag+option and with input setting
                        #        newLines[idx] = un_comment(line, comInd, lineNum)
                        #        fFlags.F_fileModified = True
                        #        fFlags = multi_line_logic(mtag, fFlags)
                        #    else:
                        #        pass

                    #else:
                        #if not fFlags.F_commented:  # uncommented line
                            #print("AAAAA")
                            # Comment lines with input tag+option without input setting
                            #if setting != userInput.setting:  # setting mismatch
                            if (inlineOptionMatch[tag+option]) and (not inlineSettingMatch[tag+option]):  # not 1 match in line
                                #print("BBBBB")
                                newLines[idx] = comment(line, comInd, lineNum)
                                fFlags.F_fileModified = True
                                #fFlags = multi_line_logic(mtag, fFlags)
                                if mtag and not fFlags.F_multiLineActive:
                                    #print("CCCCC")
                                    fFlags.F_multiLineActive = True
                                    fFlags.F_multiCommented = fFlags.F_commented
                                    fFlags.F_freezeChanges = True
                                elif mtag and fFlags.F_multiLineActive:
                                    #print("DDDDD")
                                    fFlags.F_multiLineActive = False
                                    fFlags.F_multiCommented = None
                                    fFlags.F_freezeChanges = True
                                else:
                                    pass

                ##else: # modifying input option
                #elif re.search(userInput.tag+userInput.option, tag+option):
                #    # Match input tag+option
                #    # Match setting
                #    if re.search(userInput.setting, setting):
                #        pass
                #    print("DEBUG", tag, userInput.tag)
                #    #setting = userInput.setting
                #    #tag = userInput.tag
                #    #option = userInput.option
                #    if re.search(ANY_VAR_SETTING, setting) and not fFlags.F_commented:
                #        # If variable option, use user-supplied regex to modify line
                #        strToReplace = parse_inline_regex(nonCom, setting, varErrMsg)
                #        replaceStr = userInput.setting
                #        if replaceStr == strToReplace:
                #            logging.info(f"Option already set: {replaceStr}")
                #        else:
                #            with handle_errors(errTypes=AttributeError, msg=varErrMsg):
                #                newLines[idx] = set_var_option(line, comInd, lineNum,
                #                        replaceStr, setting, strToReplace, nonCom, wholeCom)
                #            fFlags.F_fileModified = True
                #    elif fFlags.F_commented:  # commented line
                #        # Uncomment lines with input tag+option and with input setting
                #        #if inlineSettingMatch[tag+option]:
                #        if setting == userInput.setting:
                #            newLines[idx] = un_comment(line, comInd, lineNum)
                #            fFlags.F_fileModified = True
                #            fFlags = multi_line_logic(mtag, fFlags)
                #        else:
                #            pass
                #    elif not fFlags.F_commented:  # uncommented line
                #        # Comment lines with input tag+option without input setting
                #        #if setting != userInput.setting:  # setting mismatch
                #        tag = userInput.tag
                #        option = userInput.option
                #        if (inlineOptionMatch[tag+option]) and (not inlineSettingMatch[tag+option]):  # not 1 match in line
                #            newLines[idx] = comment(line, comInd, lineNum)
                #            fFlags.F_fileModified = True
                #            #fFlags = multi_line_logic(mtag, fFlags)
                #            if mtag and not fFlags.F_multiLineActive:
                #                fFlags.F_multiLineActive = True
                #                fFlags.F_multiCommented = fFlags.F_commented
                #                fFlags.F_freezeChanges = True
                #            elif mtag and fFlags.F_multiLineActive:
                #                fFlags.F_multiLineActive = False
                #                fFlags.F_multiCommented = None
                #                fFlags.F_freezeChanges = True
                #            else:
                #                pass
                #    else:
                #        pass

    # Write file
    if fFlags.F_fileModified:
        with open(validFile, 'w') as file: 
            file.writelines(newLines)
        print_and_log(f"File modified: {file.name}")
        return True
    else:
        return False



def scroll_through_files(validFiles, userInput, F_getAvailable):
    """Scroll through files, line by line. This function:
    * Returns available options if F_getAvailable is enabled.
    * Sets given options if F_getAvailable is disabled.
    * This is heart of the code. """
    allOptionsSettings = defaultdict(lambda: defaultdict(lambda: None))
    allVariableOptions = defaultdict(lambda: defaultdict(lambda: None))
    F_changesMade = False

    if F_getAvailable:
        logging.info("Scrolling through files to gather available options")
    else:
        logging.info(("Scrolling through files to set: "
                "{i.tag}{i.option} {i.setting}").format(i=userInput))

    for validFile in validFiles:
        F_processed = process_file(validFile, userInput, F_getAvailable,
                allOptionsSettings, allVariableOptions)
        if F_processed:
            F_changesMade = True

    if F_getAvailable:
        # Cut out options with a singular setting. Could try filter() here
        reducedOptionsSettings = { tg:n for tg,n in allOptionsSettings.items() if len(n) > 1}
        return reducedOptionsSettings, allVariableOptions
    else:
        return F_changesMade

def fn_compare(globSet, compareArray):
    """Compare set with unix * expressions with array of files or directories. """
    for g in globSet:
        for c in compareArray:
            if fnmatch(c, g):
                return True
    else:  # no break
        return False


def gen_valid_files():
    """Generator to get non-ignored files in non-ignored directories. """
    for dirPath, _, files in os.walk('.'):
        if not fn_compare(IGNORE_DIRS, dirPath.split(os.sep)):
            for file in files:
                if not fn_compare(IGNORE_FILES, (file,)):
                    yield f"{dirPath}/{file}"

def print_and_log(printStr):
    """Print to standard out and INFO level in log. """
    logging.info(printStr)
    if not args.quiet: 
        print(printStr)


@contextmanager
def handle_errors(errTypes, msg):
    """Use 'with:' to handle an error and print a message. """
    try:
        yield
    except errTypes as e:
        print_and_log(msg)
        exit()

def parse_and_check_input(args):
    """Parse input arguments. """
    UserInput = namedtuple('UserInput', ['tag', 'option', 'setting',])
    if args.available:
        return UserInput(tag=ANY_TAG, option=ANY_OPTION, setting=args.setting)
    else:
        # Check if both a option and a setting were input
        if args.setting is None or args.option is None:
            parser.print_usage()
            print_and_log(INCOMPLETE_INPUT_MSG)
            exit()
        # Check if setting is formatted correctly
        with handle_errors(errTypes=AttributeError, msg=INVALID_SETTING_MSG):
            setting = re.search(f"(^{VALID_INPUT_SETTING}$)", args.setting).group(0)
        # Check if option is formatted correctly
        checkTagOptionRe = re.compile(f"({ANY_TAG}+)({ANY_WORD})")
        with handle_errors(errTypes=(AttributeError), msg=INVALID_OPTION_MSG):
            tag, option = checkTagOptionRe.search(args.option).groups()
        literalTag = ''.join([f'\{s}' for s in tag])  # read as literal symbols
        return UserInput(tag=literalTag, option=option, setting=setting)

def main(args):
    """Main function. """
    logging.info("Executing main function")
    logging.info("Checking input options")
    userInput = parse_and_check_input(args)
    logging.info(f"<tag><option> <setting> = "
            f"{userInput.tag}{userInput.option} {userInput.setting}")
    logging.info("Generating valid files")
    validFiles = list(gen_valid_files())  # can run as generator
    logging.info(f"Valid files: {validFiles}")
    if args.available:
        tagsOptionsSettings, varOptions = scroll_through_files(validFiles,
                userInput=userInput, F_getAvailable=True)
        globPat = '*' if args.option is None else f"{args.option}*"
        print_available(tagsOptionsSettings, globPat=globPat)
        if len(varOptions) > 0:
            print_available(varOptions, globPat=globPat, headerMsg=None)
    else:
        F_changesMade = scroll_through_files(validFiles,
                userInput=userInput, F_getAvailable=False)
        if F_changesMade:
            print_and_log(f"See all modifications in {LOG_PATH}")

    print_and_log(f"Finished in {(time()-START_TIME):1.5f} s")

## Run main function
if __name__ == '__main__':
    main(args)
