import logging, os, re, ast
import xml.etree.ElementTree as ET

from cuckoo.common.abstracts import Processing
from cuckoo.common.exceptions import CuckooProcessingError

log = logging.getLogger(__name__)

__author__  = "Jeff White [karttoon] @noottrak"
__email__   = "jwhite@paloaltonetworks.com"
__version__ = "1.0.5"
__date__    = "21FEB2018"

def charReplace(inputString, MODFLAG):
    # OLD: ("{1}{0}{2}" -F"AMP","EX","LE")
    # NEW: "EXAMPLE"
    # Find group of obfuscated string
    obfGroup = re.search("(\"|\')(\{[0-9]{1,2}\})+(\"|\')[ -fF].+?\'.+?\'\)(?!(\"|\'|;))",inputString).group()

    # Build index and string lists
    indexList = [int(x) for x in re.findall("\d+", obfGroup.split("-")[0])]

    # This is to address scenarios where the string built is more PS commands with quotes
    stringList = re.search("(\"|\').+","-".join(obfGroup.split("-")[1:])[:-1]).group()
    stringChr = stringList[0]
    stringList = stringList.replace(stringChr + "," + stringChr, "\x00")
    stringList = stringList[1:-1]
    stringList = stringList.replace("'", "\x01").replace('"', "\x02")
    stringList = stringList.replace("\x00", stringChr + "," + stringChr)
    stringList = ast.literal_eval("[" + stringChr + stringList + stringChr + "]")

    for index,entry in enumerate(stringList):
        stringList[index] = entry.replace("\x01", "'").replace("\x02", '"')

    # Build output string
    stringOutput = ""
    for value in indexList:
        stringOutput += stringList[value]
    stringOutput = '"' + stringOutput + '")'
    # Replace original input with obfuscated group replaced

    if MODFLAG == 0:
        MODFLAG = 1
    return inputString.replace(obfGroup, stringOutput), MODFLAG

def spaceReplace(inputString, MODFLAG):
    # OLD: $var=    "EXAMPLE"
    # NEW: $var= "EXAMPLE"
    if MODFLAG == 0:
        MODFLAG = 0
    return inputString.replace("  ", " "), MODFLAG

def joinStrings(inputString, MODFLAG):
    # OLD: $var=("EX"+"AMP"+"LE")
    # NEW: $var=("EXAMPLE")
    if MODFLAG == 0:
        MODFLAG = 1
    return inputString.replace("'+'", "").replace('"+"', ""), MODFLAG

def removeNull(inputString, MODFLAG):
    # Windows/Unicode null bytes will interfere with regex
    if MODFLAG == 0:
        MODFLAG = 0
    return inputString.replace("\x00", ""), MODFLAG

def removeEscape(inputString, MODFLAG):
    # OLD: $var=\'EXAMPLE\'
    # NEW: $var='EXAMPLE'
    if MODFLAG == 0:
        MODFLAG = 0
    return inputString.replace("\\'", "'").replace('\\"', '"'), MODFLAG

def removeTick(inputString, MODFLAG):
    # OLD: $v`a`r=`"EXAMPLE"`
    # NEW: $var="EXAMPLE"
    if MODFLAG == 0:
        MODFLAG = 1
    return inputString.replace("`", ""), MODFLAG

def removeCaret(inputString, MODFLAG):
    # OLD: $v^a^r=^"EXAMPLE"^
    # NEW: $var="EXAMPLE"
    if MODFLAG == 0:
        MODFLAG = 1
    return inputString.replace("^", ""), MODFLAG

def adjustCase(inputString, MODFLAG):
    # OLD: $vAR="ExAmpLE"
    # NEW: $var="example"
    if MODFLAG == 0:
        MODFLAG = 0
    return inputString.lower(), MODFLAG

def replaceDecoder(inputString, MODFLAG):
    # OLD: (set GmBtestGmb).replace('GmB',[Char]39)
    # NEW: set 'test'
    inputString = inputString.replace("'+'", "")
    inputString = inputString.replace("'|'", "char[124]")

    if "|" in inputString:
        if "replace" not in inputString.split("|")[-1]:
            inputString = "|".join(inputString.split("|")[0:-1])
        else:
            pass

    while "replace" in inputString.split(".")[-1].lower() or "replace" in inputString.split("-")[-1].lower():

        inputString = inputString.replace("'+'", "")
        inputString = inputString.replace("'|'", "char[124]")

        if len(inputString.split(".")[-1]) > len(inputString.split("-")[-1]):

            tempString = "-".join(inputString.split("-")[0:-1])
            replaceString = inputString.split("-")[-1]

            if "[" in replaceString.split(",")[0]:
                firstPart = " ".join(replaceString.split(",")[0].split("[")[1:]).replace("'", "").replace('"', "")

            elif "'" in replaceString.split(",")[0].strip() or '"' in replaceString.split(",")[0].strip():
                firstPart = re.search("(\'.+?\'|\".+?\")", replaceString.split(",")[0]).group().replace("'", "").replace('"', "")

            else:
                firstPart = replaceString.split(",")[0].split("'")[1].replace("'", "").replace('"', "")

            secondPart = replaceString.split(",")[1].split(")")[0].replace("'", "").replace('"', "")
        else:
            tempString = ".".join(inputString.split(".")[0:-1])
            replaceString = inputString.split(".")[-1]
            firstPart = replaceString.split(",")[0].split("(")[-1].replace("'", "").replace('"', "")
            secondPart = replaceString.split(",")[1].split(")")[0].replace("'", "").replace('"', "")

        if "+" in firstPart:

            newFirst = ""

            for entry in firstPart.split("+"):
                newFirst += chr(int(re.search("[0-9]+", entry).group()))

            firstPart = newFirst

        if re.search("char", firstPart, re.IGNORECASE):
            firstPart = chr(int(re.search("[0-9]+", firstPart).group()))

        if "+" in secondPart:

            newSecond = ""

            for entry in secondPart.split("+"):
                newSecond += chr(int(re.search("[0-9]+", entry).group()))

            secondPart = newSecond

        if re.search("char", secondPart, re.IGNORECASE):
            secondPart = chr(int(re.search("[0-9]+", secondPart).group()))

        tempString = tempString.replace(firstPart, secondPart)
        inputString = tempString

        if "replace" not in inputString.split("|")[-1].lower():
            inputString = inputString.split("|")[0]

    if MODFLAG == 0:
        MODFLAG = 1

    return inputString, MODFLAG

class Curtain(Processing):
    """Parse Curtain log for PowerShell 4104 Events."""

    def run(self):

        self.key = "curtain"
        # Remove some event entries which are commonly found in all samples (noise reduction)
        noise = [
            "$global:?",
            "# Compute file-hash using the crypto object",
            "# Construct the strongly-typed crypto object",
            "HelpInfoURI = 'http://go.microsoft.com/fwlink/?linkid=285758'",
            "[System.Management.ManagementDateTimeConverter]::ToDmtfDateTime($args[0])",
            "[System.Management.ManagementDateTimeConverter]::ToDateTime($args[0])",
            "Set-Location Z:",
            "Set-Location Y:",
            "Set-Location X:",
            "Set-Location W:",
            "Set-Location V:",
            "Set-Location U:",
            "Set-Location T:",
            "Set-Location S:",
            "Set-Location R:",
            "Set-Location Q:",
            "Set-Location P:",
            "Set-Location O:",
            "Set-Location N:",
            "Set-Location M:",
            "Set-Location L:",
            "Set-Location K:",
            "Set-Location J:",
            "Set-Location I:",
            "Set-Location H:",
            "Set-Location G:",
            "Set-Location F:",
            "Set-Location E:",
            "Set-Location D:",
            "Set-Location C:",
            "Set-Location B:",
            "Set-Location A:",
            "Set-Location ..",
            "Set-Location \\",
            "$wrappedCmd = $ExecutionContext.InvokeCommand.GetCommand('Out-String',[System.Management.Automation.CommandTypes]::Cmdlet)",
            "$str.Substring($str.LastIndexOf('Verbs') + 5)",
            "[Parameter(ParameterSetName='nameSet', Position=0, ValueFromPipelineByPropertyName=$true)]",
            "[ValidateSet('Alias','Cmdlet','Provider','General','FAQ','Glossary','HelpFile'",
            "param([string[]]$paths)",
            "$origin = New-Object System.Management.Automation.Host.Coordinates",
            "Always resolve file paths using Resolve-Path -Relative.",
            "PS $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1))",
            "$this.ServiceName",
            "Read-Host 'Press Enter to continue...' | Out-Null",
            "([System.Management.Automation.CommandTypes]::Script)",
            "if ($myinv -and ($myinv.MyCommand -or ($_.CategoryInfo.Category -ne 'ParserError')))",
            "CmdletsToExport=@(",
            "CmdletsToExport",
            "FormatsToProcess",
            "AliasesToExport",
            "FunctionsToExport",
            "$_.PSParentPath.Replace",
            "$ExecutionContext.SessionState.Path.Combine",
            "get-help about_Command_Precedence"
        ]

        # Determine oldest Curtain log and remove the rest
        curtLog = os.listdir("%s/curtain/" % self.analysis_path)
        curtLog.sort()
        curtLog = curtLog[-1]

        # Leave only the most recent file
        for file in os.listdir("%s/curtain/" % self.analysis_path):
            if file != curtLog:
                try:
                    os.remove("%s/curtain/%s" % (self.analysis_path, file))
                except:
                    pass

        os.rename("%s/curtain/%s" % (self.analysis_path, curtLog), "%s/curtain/curtain.log" % self.analysis_path)

        try:
            tree = ET.parse("%s/curtain/curtain.log" % self.analysis_path)
            root = tree.getroot()
        except Exception as e:
            raise CuckooProcessingError("Failed opening curtain.log: %s" % e.message)

        pids     = {}
        COUNTER  = 0
        FILTERED = 0

        for i in range(0,len(root)):

            # Setup PID Dict
            if root[i][0][1].text == "4104":

                FILTERFLAG = 0

                PID = root[i][0][10].attrib['ProcessID']
                #TID = root[i][0][10].attrib['ThreadID']

                MESSAGE = root[i][1][2].text

                if PID not in pids:
                    pids[PID] = {
                        "pid": PID,
                        "events": [],
                        "filter": []
                    }

                # Checks for unique strings in events to filter out
                if MESSAGE != None:
                    for entry in noise:
                        if entry in MESSAGE:
                            FILTERFLAG = 1
                            FILTERED  += 1
                            pids[PID]["filter"].append({str(FILTERED): MESSAGE.strip()})

                # Save the record
                if FILTERFLAG == 0 and MESSAGE != None:

                    COUNTER += 1
                    MODFLAG = 0

                    # Attempt to further decode token replacement/other common obfuscation
                    # Original and altered will be saved
                    ALTMSG = MESSAGE.strip()

                    if re.search("\x00", ALTMSG):
                        ALTMSG, MODFLAG = removeNull(ALTMSG, MODFLAG)

                    if re.search("(\\\"|\\\')", ALTMSG):
                        ALTMSG, MODFLAG = removeEscape(ALTMSG, MODFLAG)

                    if re.search("`", ALTMSG):
                        ALTMSG, MODFLAG = removeTick(ALTMSG, MODFLAG)

                    if re.search("\^", ALTMSG):
                        ALTMSG, MODFLAG = removeCaret(ALTMSG, MODFLAG)

                    while re.search("[\x20]{2,}", ALTMSG):
                        ALTMSG, MODFLAG = spaceReplace(ALTMSG, MODFLAG)

                    # One run pre charPreplace
                    if re.search("(\"\+\"|\'\+\')", ALTMSG):
                        ALTMSG, MODFLAG = joinStrings(ALTMSG, MODFLAG)

                    while re.search("(\"|\')(\{[0-9]{1,2}\})+(\"|\')[ -fF]+(\'.+?\'\))", ALTMSG):
                        ALTMSG, MODFLAG = charReplace(ALTMSG, MODFLAG)

                    # One run post charReplace for new strings
                    if re.search("(\"\+\"|\'\+\')", ALTMSG):
                        ALTMSG, MODFLAG = joinStrings(ALTMSG, MODFLAG)

                    if "replace" in ALTMSG.lower():
                        try:
                            ALTMSG, MODFLAG = replaceDecoder(ALTMSG, MODFLAG)
                        except Exception as e:
                            log.error("Curtain processing error for entry - %s" % e)

                    # Remove camel case obfuscation as last step
                    ALTMSG, MODFLAG = adjustCase(ALTMSG, MODFLAG)

                    if MODFLAG == 0:
                        ALTMSG = "No alteration of event."

                    # Save the output
                    pids[PID]["events"].append({str(COUNTER): {"original": MESSAGE.strip(), "altered": ALTMSG}})

        remove = []

        # Find empty PID
        for pid in pids:
            if len(pids[pid]["events"]) == 0:
                if pid not in remove:
                    remove.append(pid)

        # Remove PIDs
        for pid in remove:
            del pids[pid]

        # Reorder event counts
        for pid in pids:
            tempEvents = []
            eventCount = len(pids[pid]["events"])
            for index, entry in enumerate(pids[pid]["events"]):
                tempEvents.append({"%02d" % (eventCount - index): entry.values()[0]})
            pids[pid]["events"] = tempEvents

            tempEvents = []
            eventCount = len(pids[pid]["filter"])
            for index, entry in enumerate(pids[pid]["filter"]):
                tempEvents.append({"%02d" % (eventCount - index): entry.values()[0]})
            pids[pid]["filter"] = tempEvents

        return pids
