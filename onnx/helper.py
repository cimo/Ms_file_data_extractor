import os
import re
import shutil
import subprocess
import cv2
import icu
import numpy
import datetime
import unicodedata
import xml.etree.ElementTree

stderrFileDescriptor = os.dup(2)
nullFileDescriptor = os.open(os.devnull, os.O_WRONLY)

os.dup2(nullFileDescriptor, 2)

import onnxruntime

os.dup2(stderrFileDescriptor, 2)

os.close(nullFileDescriptor)
os.close(stderrFileDescriptor)

def memoryFree(isGpu):
    if isGpu:
        return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], capture_output=True).stdout.decode().split("\n")[0]) * 1024 * 1024

    with open("/proc/meminfo", encoding="utf-8") as file:
        return int([line for line in file if line.startswith("MemAvailable")][0].split()[1]) * 1024

def memoryLimitBuild():
    resultObject = {"gpu": 0, "cpu": int(memoryFree(False) * levelMemory)}

    onnxruntime.create_and_register_allocator(onnxruntime.OrtMemoryInfo("Cpu", onnxruntime.OrtAllocatorType.ORT_ARENA_ALLOCATOR, 0, onnxruntime.OrtMemType.DEFAULT), onnxruntime.OrtArenaCfg({"max_mem": resultObject["cpu"], "arena_extend_strategy": 1}))

    if "CUDAExecutionProvider" in onnxruntime.get_available_providers() and shutil.which("nvidia-smi") != None:
        resultObject["gpu"] = int(memoryFree(True) * levelMemory)

        onnxruntime.create_and_register_allocator_v2("CUDAExecutionProvider", onnxruntime.OrtMemoryInfo("Cuda", onnxruntime.OrtAllocatorType.ORT_ARENA_ALLOCATOR, 0, onnxruntime.OrtMemType.DEFAULT), {}, onnxruntime.OrtArenaCfg({"max_mem": resultObject["gpu"], "arena_extend_strategy": 1}))

    return resultObject

def onnxSessionBuild(pathModel):
    option = onnxruntime.SessionOptions()

    option.log_severity_level = 3

    option.add_session_config_entry("session.use_env_allocators", "1")

    option.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL

    option.intra_op_num_threads = len(os.sched_getaffinity(0))
    option.inter_op_num_threads = 1

    option.enable_cpu_mem_arena = False
    option.enable_mem_pattern = True
    option.enable_mem_reuse = True

    option.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL

    providerPreferredList = [
        "CUDAExecutionProvider",
        "OpenVINOExecutionProvider",
        "CPUExecutionProvider"
    ]

    providerOptionObject = {
        "CUDAExecutionProvider": {"arena_extend_strategy": "kSameAsRequested", "cudnn_conv_algo_search": "HEURISTIC"}
    }

    providerAvailableList = onnxruntime.get_available_providers()

    providerList = [(provider, providerOptionObject[provider] if provider in providerOptionObject else {}) for provider in providerPreferredList if provider in providerAvailableList]

    inference = onnxruntime.InferenceSession(pathModel, sess_options=option, providers=providerList)

    print(f"Provider available: {providerAvailableList}")
    print(f"Provider active: {inference.get_providers()}\n")

    return inference

def onnxMemoryRelease(onnxSession):
    if memoryLimitObject["gpu"] == 0:
        return

    runOption = onnxruntime.RunOptions()

    runOption.add_run_config_entry("memory.enable_memory_arena_shrinkage", "gpu:0")

    inputNode = onnxSession.get_inputs()[0]

    onnxSession.run(None, {inputNode.name: numpy.zeros([size if isinstance(size, int) else 1 for size in inputNode.shape], dtype=numpy.float32)}, runOption)

# Custom
def tokenScore(valueList, index):
    value = valueList.astype(numpy.float64)

    value = value - value.max()

    return float(value[index] - numpy.log(numpy.exp(value).sum()))

def tensorNormalize(image, meanList, standardList):
    tensor = (image.astype(numpy.float32) / 255.0 - meanList) / standardList

    return numpy.expand_dims(tensor.transpose((2, 0, 1)), axis=0).astype(numpy.float32)

def imageInkBuild(image):
    return cv2.threshold(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

def detrDetect(imageRgb, imageSize, interpolation, onnxSession):
    imageHeight, imageWidth = imageRgb.shape[0:2]

    imageResized = cv2.resize(imageRgb, (imageSize, imageSize), interpolation=interpolation).astype(numpy.float32) / 255.0

    tensorFeedObject = {
        "image": numpy.expand_dims(imageResized.transpose((2, 0, 1)), axis=0).astype(numpy.float32),
        "im_shape": numpy.array([[imageSize, imageSize]], dtype=numpy.float32),
        "scale_factor": numpy.array([[imageSize / float(imageHeight), imageSize / float(imageWidth)]], dtype=numpy.float32)
    }

    tensorOutputList = onnxSession.run(None, tensorFeedObject)

    boxCount = int(tensorOutputList[1][0])

    resultList = []

    for a in range(boxCount):
        value = tensorOutputList[0][a]

        x1 = max(0, min(int(round(float(value[2]))), imageWidth))
        y1 = max(0, min(int(round(float(value[3]))), imageHeight))
        x2 = max(0, min(int(round(float(value[4]))), imageWidth))
        y2 = max(0, min(int(round(float(value[5]))), imageHeight))

        if x2 <= x1 or y2 <= y1:
            continue

        resultList.append({
            "classId": int(value[0]),
            "score": float(value[1]),
            "bbox": [x1, y1, x2, y2]
        })

    return resultList

def wideCheck(character):
    if character == "":
        return False

    return icu.Char.getIntPropertyValue(character, icu.UProperty.EAST_ASIAN_WIDTH) in widthWideList

def wideTextCheck(text):
    return len([character for character in text if wideCheck(character)]) * 2 > len(text)

def wideMarkCheck(character):
    return wideCheck(character) and unicodedata.category(character)[0] == "P"

def spacelessCheck(character):
    if wideCheck(character):
        return True

    return icu.Char.getIntPropertyValue(character, icu.UProperty.LINE_BREAK) == lineBreakComplex

def whitespaceCheck(character):
    if character == "":
        return False

    return icu.Char.isUWhiteSpace(character)

def characterNormalize(text, blockList):
    result = ""

    for a in range(len(text)):
        if icu.Char.getIntPropertyValue(text[a], icu.UProperty.BLOCK) in blockList:
            result += icu.Normalizer2.getNFKCInstance().normalize(text[a])
        else:
            result += text[a]

    return result

def ideographPageResolve(pageList):
    textList = []

    for a in range(len(pageList)):
        elementList = pageList[a]["elementList"]

        for b in range(len(elementList)):
            if elementList[b]["type"] == "text":
                textList.append(elementList[b]["text"])

    resolveObject = ideographResolveBuild(ideographLocaleDetect("".join(textList)))

    for a in range(len(pageList)):
        elementList = pageList[a]["elementList"]

        for b in range(len(elementList)):
            if elementList[b]["type"] == "text":
                elementList[b]["text"] = ideographTextResolve(elementList[b]["text"], resolveObject)

def ideographLocaleDetect(text):
    result = ""

    countBest = 0

    for locale in ideographExemplarObject:
        count = 0

        for a in range(len(text)):
            if text[a] in ideographExemplarObject[locale]:
                count += 1

        if count > countBest:
            result = locale
            countBest = count

    return result

def ideographResolveBuild(locale):
    resultObject = {}

    for character in ideographEquivalentObject:
        resultObject[character] = ideographEquivalentObject[character]

        if locale == "" or resultObject[character] in ideographExemplarObject[locale] or resultObject[character] not in ideographVariantObject:
            continue

        variantList = ideographVariantObject[resultObject[character]]

        for a in range(len(variantList)):
            if variantList[a] in ideographExemplarObject[locale]:
                resultObject[character] = variantList[a]

                break

    return resultObject

def ideographTextResolve(text, resolveObject):
    result = ""

    for a in range(len(text)):
        result += resolveObject[text[a]] if text[a] in resolveObject else text[a]

    return result

def ideographEquivalentBuild():
    resultObject = {}

    with open(f"{os.path.dirname(__file__)}/character/equivalent.txt", encoding="utf-8") as file:
        lineList = file.read().split("\n")

    for a in range(len(lineList)):
        match = re.match(r"^([0-9A-F]+)(?:\.\.([0-9A-F]+))?\s*;\s*([0-9A-F]+)", lineList[a])

        if match is None:
            continue

        last = match.group(2) if match.group(2) is not None else match.group(1)

        for code in range(int(match.group(1), 16), int(last, 16) + 1):
            resultObject[chr(code)] = chr(int(match.group(3), 16))

    return resultObject

def ideographVariantBuild():
    resultObject = {}

    with open(f"{os.path.dirname(__file__)}/character/variant.txt", encoding="utf-8") as file:
        lineList = file.read().split("\n")

    for a in range(len(lineList)):
        match = re.match(r"^U\+([0-9A-F]+)\s+kZVariant\s+(.+)$", lineList[a])

        if match is None:
            continue

        codeList = re.findall(r"U\+([0-9A-F]+)", match.group(2))

        variantList = []

        for b in range(len(codeList)):
            variantList.append(chr(int(codeList[b], 16)))

        resultObject[chr(int(match.group(1), 16))] = variantList

    return resultObject

def ideographExemplarBuild():
    resultObject = {}

    localeList = ["ja", "zh", "zh_Hant"]

    for a in range(len(localeList)):
        localeData = icu.LocaleData(localeList[a])

        resultObject[localeList[a]] = set(localeData.getExemplarSet(0, icu.ULocaleDataExemplarSetType.ES_STANDARD)) | set(localeData.getExemplarSet(0, icu.ULocaleDataExemplarSetType.ES_AUXILIARY))

    return resultObject

def spaceSkipCheck(textPrevious, text):
    if whitespaceCheck(textPrevious[-1:]) or whitespaceCheck(text[0:1]):
        return True

    return wideCheck(textPrevious[-1:]) and wideCheck(text[0:1])

def gapMedianCalculate(charList):
    gapList = []

    for a in range(1, len(charList)):
        gapList.append(charList[a]["start"] - charList[a - 1]["end"])

    gapList.sort()

    return gapList[int(len(gapList) / 2)] if len(gapList) > 0 else 0

def spaceGapCheck(characterPrevious, characterNext, gap, size, spaceWidth, gapMedian):
    if wideCheck(characterPrevious) and wideCheck(characterNext):
        return False

    if gap > size * levelSpaceChar:
        return True

    if unicodedata.category(characterPrevious) == "Nd" and unicodedata.category(characterNext) == "Nd":
        return False

    return spaceWidth > 0 and gapMedian < spaceWidth * levelSpaceWord and gap > spaceWidth * levelSpaceWord

def sizeDominant(itemList):
    weightObject = {}

    for a in range(len(itemList)):
        size = round(itemList[a]["size"], 1)

        weightObject[size] = weightObject.get(size, 0) + len(itemList[a]["text"])

    result = 0
    weightBest = 0

    for size in weightObject:
        if weightObject[size] > weightBest:
            result = size
            weightBest = weightObject[size]

    return result

def boxFromPointList(pointList):
    xList = []
    yList = []

    for a in range(len(pointList)):
        xList.append(pointList[a][0])
        yList.append(pointList[a][1])

    return [min(xList), min(yList), max(xList), max(yList)]

def boxSizeMedian(bboxList):
    sizeList = sorted(min(bboxObject[2] - bboxObject[0], bboxObject[3] - bboxObject[1]) for bboxObject in bboxList)

    return sizeList[int(len(sizeList) / 2)] if len(sizeList) > 0 else 1

def boxExpand(bboxList, bboxOtherList):
    return [
        min(bboxList[0], bboxOtherList[0]),
        min(bboxList[1], bboxOtherList[1]),
        max(bboxList[2], bboxOtherList[2]),
        max(bboxList[3], bboxOtherList[3])
    ]

def boxArea(bboxList):
    return (bboxList[2] - bboxList[0]) * (bboxList[3] - bboxList[1])

def boxCenterInsideCheck(bboxList, boxOuterList):
    centerX = (bboxList[0] + bboxList[2]) / 2
    centerY = (bboxList[1] + bboxList[3]) / 2

    return centerX >= boxOuterList[0] and centerX <= boxOuterList[2] and centerY >= boxOuterList[1] and centerY <= boxOuterList[3]

def boxDistance(bboxList, bboxOtherList):
    distanceX = max(0, bboxList[0] - bboxOtherList[2], bboxOtherList[0] - bboxList[2])
    distanceY = max(0, bboxList[1] - bboxOtherList[3], bboxOtherList[1] - bboxList[3])

    return (distanceX ** 2 + distanceY ** 2) ** 0.5

def boxIntersection(bboxList, bboxOtherList):
    x1 = max(bboxList[0], bboxOtherList[0])
    y1 = max(bboxList[1], bboxOtherList[1])
    x2 = min(bboxList[2], bboxOtherList[2])
    y2 = min(bboxList[3], bboxOtherList[3])

    if x2 <= x1 or y2 <= y1:
        return 0

    return (x2 - x1) * (y2 - y1)

def lineGapMedian(itemList):
    gapList = []

    for a in range(len(itemList)):
        gapList += [0 for b in range(len(itemList[a]["text"]) - 1)]

        if a > 0:
            gapList.append(itemList[a]["bbox"][0] - itemList[a - 1]["bbox"][2])

    gapList.sort()

    return gapList[int(len(gapList) / 2)] if len(gapList) > 0 else 0

def lineText(itemList):
    result = ""

    gapMedian = lineGapMedian(itemList)

    for a in range(len(itemList)):
        text = itemList[a]["text"]

        if a > 0:
            gap = itemList[a]["bbox"][0] - itemList[a - 1]["bbox"][2]

            if gap >= itemList[a]["size"] * levelSpaceGap and result.endswith(" ") == False and text.startswith(" ") == False and (spaceSkipCheck(result, text) == False or gap > gapMedian):
                result += " "

        result += text

    return " ".join(result.encode("utf-16", "surrogatepass").decode("utf-16", "replace").split())

def lineBuild(itemList):
    lineList = []

    itemSortedList = sorted(itemList, key=lambda itemObject: (itemObject["bbox"][1] + itemObject["bbox"][3]) / 2)

    for a in range(len(itemSortedList)):
        bboxList = itemSortedList[a]["bbox"]

        lineObject = None

        for b in range(len(lineList) - 1, -1, -1):
            bandList = lineList[b]["band"]

            overlap = min(bboxList[3], bandList[1]) - max(bboxList[1], bandList[0])

            if overlap >= min(bboxList[3] - bboxList[1], bandList[1] - bandList[0]) * levelLineOverlap:
                lineObject = lineList[b]

                break

        if lineObject == None:
            lineList.append({"bbox": list(bboxList), "band": [bboxList[1], bboxList[3]], "itemList": [itemSortedList[a]]})

            continue

        lineObject["itemList"].append(itemSortedList[a])
        lineObject["bbox"] = boxExpand(lineObject["bbox"], bboxList)

    lineList.sort(key=lambda lineObject: lineObject["bbox"][1])

    for a in range(len(lineList)):
        lineList[a]["itemList"].sort(key=lambda itemObject: itemObject["bbox"][0])

        lineList[a]["text"] = lineText(lineList[a]["itemList"])

    return lineList

def segmentMerge(itemList):
    result = dict(itemList[0])

    for a in range(1, len(itemList)):
        result["bbox"] = boxExpand(result["bbox"], itemList[a]["bbox"])

    result["text"] = lineText(itemList)
    result["size"] = sizeDominant(itemList)

    return result

def segmentBuild(itemList):
    resultList = []

    lineList = lineBuild(itemList)

    for a in range(len(lineList)):
        partList = []

        for b in range(len(lineList[a]["itemList"])):
            itemObject = lineList[a]["itemList"][b]

            if len(partList) > 0 and itemObject["bbox"][0] - partList[len(partList) - 1]["bbox"][2] >= itemObject["size"] * levelSpaceGap:
                resultList.append(segmentMerge(partList))

                partList = []

            partList.append(itemObject)

        if len(partList) > 0:
            resultList.append(segmentMerge(partList))

    return resultList

def blockShiftCheck(itemObject, itemOtherObject):
    bboxList = itemObject["bbox"]
    bboxOtherList = itemOtherObject["bbox"]

    if min(bboxList[3], bboxOtherList[3]) <= max(bboxList[1], bboxOtherList[1]):
        return False

    return abs((bboxList[1] + bboxList[3]) / 2 - (bboxOtherList[1] + bboxOtherList[3]) / 2) > min(bboxList[3] - bboxList[1], bboxOtherList[3] - bboxOtherList[1]) * levelSpaceGap

def blockLimit(itemList):
    itemSortedList = sorted(itemList, key=lambda itemObject: itemObject["bbox"][0])

    end = itemSortedList[0]["bbox"][2]

    for a in range(1, len(itemSortedList)):
        start = itemSortedList[a]["bbox"][0]

        if start - end >= itemSortedList[a]["size"] * levelSpaceWord:
            leftList = [itemObject for itemObject in itemList if itemObject["bbox"][2] <= end]
            rightList = [itemObject for itemObject in itemList if itemObject["bbox"][0] >= start]

            if len([1 for itemObject in leftList for itemOtherObject in rightList if blockShiftCheck(itemObject, itemOtherObject)]) > 0:
                return start

        end = max(end, itemSortedList[a]["bbox"][2])

    return None

def blockText(itemList):
    result = ""

    limit = blockLimit(itemList) if len(itemList) > 1 else None

    if limit != None:
        return textJoin(blockText([itemObject for itemObject in itemList if itemObject["bbox"][0] < limit]), blockText([itemObject for itemObject in itemList if itemObject["bbox"][0] >= limit]))

    lineList = lineBuild(itemList)

    for a in range(len(lineList)):
        result = textJoin(result, lineList[a]["text"])

    return result

def gridPositionList(cellObject):
    return [(cellObject["row"] + a, cellObject["column"] + b) for a in range(cellObject["rowSpan"]) for b in range(cellObject["columnSpan"]) if a + b > 0]

def gridRowList(cellList, countRow, countColumn):
    coveredList = []

    for a in range(len(cellList)):
        coveredList += gridPositionList(cellList[a])

    resultList = [[{"text": "", "rowSpan": 1, "columnSpan": 1, "isOrigin": (a, b) not in coveredList} for b in range(countColumn)] for a in range(countRow)]

    for a in range(len(cellList)):
        cellObject = cellList[a]

        resultList[cellObject["row"]][cellObject["column"]] = {"text": cellObject["text"], "rowSpan": cellObject["rowSpan"], "columnSpan": cellObject["columnSpan"], "isOrigin": True}

    return resultList

def numberText(text):
    value = float(text)

    if value == int(value):
        return str(int(value))

    return f"{value:.{countNumberDigit}g}"

def numberCycleBuild():
    locale = icu.Locale("zh@calendar=chinese")

    calendar = icu.Calendar.createInstance(locale)

    formatObject = icu.SimpleDateFormat("U", locale)

    itemList = []

    for a in range(60):
        time = float(datetime.datetime(2000 + a, 6, 1).timestamp())

        calendar.setTime(time)

        itemList.append({"index": calendar.get(icu.UCalendarDateFields.YEAR), "name": formatObject.format(time)})

    nameList = [itemObject["name"] for itemObject in sorted(itemList, key=lambda itemObject: itemObject["index"])]

    return {
        "ideographTraditional": [name[0:1] for name in nameList[0:10]],
        "ideographZodiac": [name[1:2] for name in nameList[0:12]],
        "ideographZodiacTraditional": nameList,
        "ganada": [chr(44032 + a * 588) for a in range(19) if "SSANG" not in unicodedata.name(chr(4352 + a))]
    }

def numberSystemBuild():
    resultObject = {}

    for format in numberSystemLocaleObject:
        resultObject[format] = icu.NumberFormat.createInstance(icu.Locale(numberSystemLocaleObject[format]))
        resultObject[format].setGroupingUsed(False)

    return resultObject

def numberTextMarker(value, format, language):
    locale = icu.Locale(language.replace("-", "_"))

    if format == "ordinal":
        return icu.RuleBasedNumberFormat(icu.URBNFRuleSetTag.ORDINAL, locale).format(value)

    formatObject = icu.RuleBasedNumberFormat(icu.URBNFRuleSetTag.SPELLOUT, locale)

    ruleList = [rule for rule in numberTextRuleObject[format] if re.search(f"^{rule}:", formatObject.getRules(), re.M) is not None]

    if len(numberTextRuleObject[format]) > 0 and len(ruleList) == 0:
        return ""

    if len(ruleList) > 0:
        formatObject.setDefaultRuleSet(ruleList[0])

    text = "".join(character for character in formatObject.format(value) if unicodedata.category(character) != "Cf")

    return text[0:1].upper() + text[1:]

def numberMarker(value, format, language):
    if format in numberCycleObject:
        return numberCycleObject[format][value - 1] if value > 0 and value <= len(numberCycleObject[format]) else ""

    if format in numberSystemObject:
        return "".join(character for character in numberSystemObject[format].format(value) if unicodedata.category(character)[0] != "P")

    if format in numberTextRuleObject:
        return numberTextMarker(value, format, language) if language != "" else ""

    if format == "decimal":
        return str(value)

    if format == "decimalZero":
        return str(value).zfill(2)

    if format == "decimalFullWidth":
        return "".join(chr(ord(character) + 65248) for character in str(value))

    if format == "decimalEnclosedCircle":
        return unicodedata.lookup(f"CIRCLED {'DIGIT' if value < 10 else 'NUMBER'} {numberSpellObject['en'].format(value).replace('-', ' ').upper()}")

    if format in ["lowerLetter", "upperLetter"]:
        letter = chr((97 if format == "lowerLetter" else 65) + (value - 1) % 26)

        return letter * ((value - 1) // 26 + 1)

    if format in numberRomanObject:
        return numberRomanObject[format].format(value)

    return numberSpellObject[numberLocaleObject[format]].format(value)

def symbolBuild():
    resultObject = {}

    with open(f"{os.path.dirname(__file__)}/character/dingbat.txt", encoding="utf-8") as file:
        for line in file:
            partList = line.strip().split(",")

            if line.startswith("#") == False and len(partList) > 3 and partList[1].isdigit():
                resultObject.setdefault(partList[0].casefold(), {})[int(partList[1])] = chr(int(partList[3]))

    resultObject["symbol"] = {}

    with open(f"{os.path.dirname(__file__)}/character/symbol.txt", encoding="utf-8") as file:
        for line in file:
            partList = line.split("\t")

            if line.startswith("#") == False and len(partList) > 1 and int(partList[1], 16) not in resultObject["symbol"]:
                resultObject["symbol"][int(partList[1], 16)] = chr(int(partList[0], 16))

    return resultObject

def symbolText(text, font):
    result = ""

    for character in text:
        code = ord(character) - symbolPrivateStart if ord(character) >= symbolPrivateStart else ord(character)

        result += symbolObject[font][code] if code in symbolObject[font] else character

    return result

def drawingRunSymbolWrite(runNode, fontLatin, fontSymbol):
    propertyNode = runNode.find(f"{{{namespaceDrawing}}}rPr")
    textNode = runNode.find(f"{{{namespaceDrawing}}}t")

    if textNode is None or textNode.text is None:
        return

    fontLatinNode = propertyNode.find(f"{{{namespaceDrawing}}}latin") if propertyNode is not None else None
    fontSymbolNode = propertyNode.find(f"{{{namespaceDrawing}}}sym") if propertyNode is not None else None

    if fontLatinNode is not None:
        fontLatin = fontLatinNode.attrib.get("typeface", "").casefold()

    if fontSymbolNode is not None:
        fontSymbol = fontSymbolNode.attrib.get("typeface", "").casefold()

    result = ""

    for character in textNode.text:
        font = fontSymbol if ord(character) >= symbolPrivateStart and fontSymbol in symbolObject else fontLatin

        result += symbolText(character, font) if font in symbolObject else character

    textNode.text = result

def drawingSymbolWrite(rootNode):
    for runNode in rootNode.iter(f"{{{namespaceDrawing}}}r"):
        drawingRunSymbolWrite(runNode, "", "")

def xmlRootBuild(pathFile, zipFile):
    if pathFile not in zipFile.namelist():
        return None

    return xml.etree.ElementTree.fromstring(re.sub(patternNamespaceStrict, replaceNamespaceStrict, zipFile.read(pathFile)))

def xmlNodeTag(node):
    return node.tag.split("}")[1] if "}" in node.tag else node.tag

def xmlNodeValue(node, namespace):
    return node.attrib.get(f"{{{namespace}}}val", "")

def xmlAttributeValue(node, nameList):
    for a in range(len(nameList)):
        for name in node.attrib:
            if name.endswith(f"}}{nameList[a]}") and node.attrib[name] != "":
                return node.attrib[name]

    return ""

def xmlFallbackRemove(node):
    for childNode in list(node):
        if xmlNodeTag(childNode) == "Fallback":
            node.remove(childNode)
        else:
            xmlFallbackRemove(childNode)

def xmlControlValue(controlNode):
    textContent = ""

    optionList = []

    isPlaceholder = False

    for childNode in controlNode:
        tagChild = xmlNodeTag(childNode)

        if tagChild == "sdtContent":
            for textNode in childNode.iter():
                if xmlNodeTag(textNode) == "t" and textNode.text is not None:
                    textContent += textNode.text

        if tagChild != "sdtPr":
            continue

        for propertyNode in childNode:
            tagProperty = xmlNodeTag(propertyNode)

            if tagProperty == "showingPlcHdr":
                isPlaceholder = True

            if tagProperty == "checkbox":
                isChecked = len([checkNode for checkNode in propertyNode if xmlNodeTag(checkNode) == "checked" and xmlAttributeValue(checkNode, ["val"]) not in valueFalseList]) > 0

                return textOptionMark if isChecked else textOptionEmpty

            if tagProperty in tagControlList:
                for itemNode in propertyNode:
                    option = xmlAttributeValue(itemNode, ["displayText", "value"])

                    if option != "":
                        optionList.append(option)

    textContent = textContent.strip()

    valueList = []

    isSelect = False

    for a in range(len(optionList)):
        if isPlaceholder and optionList[a] == textContent:
            continue

        isMark = isPlaceholder == False and optionList[a] == textContent

        if isMark:
            isSelect = True

        valueList.append(f"{textOptionMark if isMark else textOptionEmpty} {optionList[a]}")

    if len(valueList) > 0 and (isPlaceholder or isSelect):
        return separatorOption.join(valueList)

    if isPlaceholder:
        return ""

    return None

def xmlTextCollect(node, characterObject, tagSkip):
    result = ""

    tag = xmlNodeTag(node)

    if tag == tagSkip:
        return result

    if tag == "sdt":
        value = xmlControlValue(node)

        if value != None:
            return value

    if tag == "t":
        result += node.text if node.text is not None else ""
    elif tag in characterObject:
        result += characterObject[tag]

    for childNode in node:
        result += xmlTextCollect(childNode, characterObject, tagSkip)

    return result

def xmlParagraphText(paragraphNode, characterObject, tagSkip):
    return " ".join(xmlTextCollect(paragraphNode, characterObject, tagSkip).split())

def noteMark(name):
    return f"[^{name}]"

def noteText(name, author, text):
    textAuthor = text if author == "" or text.startswith(f"{author}:") else f"{author}: {text}"

    return f"{noteMark(name)}: {textAuthor}"

def xmlRelationshipBuild(pathFile, zipFile):
    resultObject = {}

    relationshipRootNode = xmlRootBuild(f"{os.path.dirname(pathFile)}/_rels/{os.path.basename(pathFile)}.rels", zipFile)

    if relationshipRootNode is not None:
        for node in relationshipRootNode.iter(f"{{{namespacePackage}}}Relationship"):
            target = node.attrib.get("Target", "")

            resultObject[node.attrib.get("Id", "")] = {
                "path": target[1:] if target.startswith("/") else os.path.normpath(f"{os.path.dirname(pathFile)}/{target}"),
                "type": node.attrib.get("Type", "")
            }

    return resultObject

def xmlRelationshipNodeList(pathFile, zipFile, tag):
    resultList = []

    rootNode = xmlRootBuild(pathFile, zipFile)

    pathObject = xmlRelationshipBuild(pathFile, zipFile)

    if rootNode is not None:
        for node in rootNode.iter(tag):
            relationshipId = node.attrib.get(f"{{{namespaceRelationship}}}id", "")

            if relationshipId in pathObject:
                resultList.append({"node": node, "path": pathObject[relationshipId]["path"]})

    return resultList

def xmlChartItemList(chartRootNode):
    resultList = []

    titleText = ""

    titleNode = chartRootNode.find(f".//{{{namespaceChart}}}title")

    if titleNode is not None:
        for node in titleNode.iter(f"{{{namespaceDrawing}}}t"):
            titleText += node.text if node.text is not None else ""

    if titleText.strip() != "":
        resultList.append({"kind": "text", "label": labelText, "text": " ".join(titleText.split())})

    nameList = []
    categoryList = []
    valueObjectList = []

    for serieNode in chartRootNode.iter(f"{{{namespaceChart}}}ser"):
        nameText = ""

        textNode = serieNode.find(f"{{{namespaceChart}}}tx")

        if textNode is not None:
            for node in textNode.iter(f"{{{namespaceChart}}}v"):
                nameText = node.text if node.text is not None else ""

                break

        categoryObject = {}

        categoryNodeList = [node for node in serieNode if xmlNodeTag(node) in tagChartCategoryList]

        if len(categoryNodeList) > 0:
            for node in categoryNodeList[0].iter(f"{{{namespaceChart}}}pt"):
                valueNode = node.find(f"{{{namespaceChart}}}v")

                if valueNode is not None and valueNode.text is not None:
                    categoryObject[node.attrib.get("idx", "")] = numberText(valueNode.text) if re.fullmatch(patternNumber, valueNode.text) is not None else valueNode.text

        valueObject = {}

        valueNodeList = [node for node in serieNode if xmlNodeTag(node) in tagChartValueList]

        if len(valueNodeList) > 0:
            for node in valueNodeList[0].iter(f"{{{namespaceChart}}}pt"):
                valueNode = node.find(f"{{{namespaceChart}}}v")

                if valueNode is not None and valueNode.text is not None:
                    index = node.attrib.get("idx", "")

                    category = categoryObject[index] if index in categoryObject else index

                    valueObject[category] = numberText(valueNode.text) if re.fullmatch(patternNumber, valueNode.text) is not None else valueNode.text

                    if category not in categoryList:
                        categoryList.append(category)

        nameList.append(nameText)
        valueObjectList.append(valueObject)

    if len(categoryList) == 0:
        return resultList

    cellList = [{"row": 0, "column": a + 1, "rowSpan": 1, "columnSpan": 1, "text": nameList[a]} for a in range(len(nameList))]

    for a in range(len(categoryList)):
        cellList.append({"row": a + 1, "column": 0, "rowSpan": 1, "columnSpan": 1, "text": categoryList[a]})

        for b in range(len(valueObjectList)):
            if categoryList[a] in valueObjectList[b]:
                cellList.append({"row": a + 1, "column": b + 1, "rowSpan": 1, "columnSpan": 1, "text": valueObjectList[b][categoryList[a]]})

    resultList.append({"kind": "table", "label": labelTable, "rowList": gridRowList(cellList, len(categoryList) + 1, len(nameList) + 1)})

    return resultList

def hyphenCheck(text):
    return len(text) > 1 and (unicodedata.category(text[-1:]) == "Pd" or text[-1:] == characterHyphenSoft) and unicodedata.category(text[-2:-1])[0] == "L"

def sentenceEndCheck(text):
    result = text.strip()

    while len(result) > 0:
        category = unicodedata.category(result[-1:])

        if category == "Pe":
            indexOpen = max([a for a in range(len(result)) if unicodedata.category(result[a]) == "Ps"] + [-1])

            result = result[0:indexOpen].strip() if indexOpen >= 0 else result[0:-1].strip()

            continue

        if category == "Pf" or icu.Char.hasBinaryProperty(result[-1:], icu.UProperty.QUOTATION_MARK):
            result = result[0:-1].strip()

            continue

        break

    return len(result) == 0 or icu.Char.hasBinaryProperty(result[-1:], icu.UProperty.S_TERM)

def wordKey(text):
    result = text

    while len(result) > 0 and unicodedata.category(result[0:1])[0] not in categoryWordList:
        result = result[1:]

    while len(result) > 0 and unicodedata.category(result[-1:])[0] not in categoryWordList:
        result = result[0:-1]

    return result.casefold()

def textJoin(text, textNext):
    if text == "":
        return textNext

    if textNext == "":
        return text

    if hyphenCheck(text) and unicodedata.category(textNext[0:1])[0] == "L":
        return f"{text}{characterHyphenMark}{textNext}"

    if (spacelessCheck(text[-1:]) and spacelessCheck(textNext[0:1])) or wideMarkCheck(text[-1:]) or wideMarkCheck(textNext[0:1]):
        return f"{text}{textNext}"

    return f"{text} {textNext}"

levelMemory = 0.8

memoryLimitObject = memoryLimitBuild()

levelLineDouble = 1.7
levelRuleLength = 1.5

levelSpaceChar = 1.0
levelSpaceWord = 0.5
levelSpaceGap = 0.15
levelLineOverlap = 0.5
levelOptionSide = 2.0

namespaceDrawing = "http://schemas.openxmlformats.org/drawingml/2006/main"
namespaceChart = "http://schemas.openxmlformats.org/drawingml/2006/chart"
namespaceRelationship = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
namespacePackage = "http://schemas.openxmlformats.org/package/2006/relationships"

patternNamespaceStrict = rb"http://purl\.oclc\.org/ooxml/(\w+)/"
replaceNamespaceStrict = rb"http://schemas.openxmlformats.org/\1/2006/"
patternNumber = r"-?\d+(\.\d+)?([eE][+-]?\d+)?"

countNumberDigit = 15

numberLocaleObject = {"chineseCounting": "zh", "chineseCountingThousand": "zh", "chineseLegalSimplified": "zh_financial", "taiwaneseCounting": "zh_Hant", "taiwaneseCountingThousand": "zh_Hant", "japaneseCounting": "ja", "koreanCounting": "ko"}
numberSpellObject = {"en": icu.RuleBasedNumberFormat(icu.URBNFRuleSetTag.SPELLOUT, icu.Locale("en")), "zh": icu.RuleBasedNumberFormat(icu.URBNFRuleSetTag.SPELLOUT, icu.Locale("zh")), "zh_financial": icu.RuleBasedNumberFormat(icu.URBNFRuleSetTag.SPELLOUT, icu.Locale("zh")), "zh_Hant": icu.RuleBasedNumberFormat(icu.URBNFRuleSetTag.SPELLOUT, icu.Locale("zh_Hant")), "ja": icu.RuleBasedNumberFormat(icu.URBNFRuleSetTag.SPELLOUT, icu.Locale("ja")), "ko": icu.RuleBasedNumberFormat(icu.URBNFRuleSetTag.SPELLOUT, icu.Locale("ko"))}
numberSpellObject["zh_financial"].setDefaultRuleSet("%spellout-cardinal-financial")
numberRomanObject = {"upperRoman": icu.NumberFormat.createInstance(icu.Locale("en@numbers=roman")), "lowerRoman": icu.NumberFormat.createInstance(icu.Locale("en@numbers=romanlow"))}
numberCycleObject = numberCycleBuild()
numberSystemLocaleObject = {"ideographDigital": "zh@numbers=hanidec", "hebrew1": "he@numbers=hebr", "hindiNumbers": "hi@numbers=deva", "thaiNumbers": "th@numbers=thai"}
numberSystemObject = numberSystemBuild()
numberTextRuleObject = {"ordinal": [], "cardinalText": [], "ordinalText": ["%spellout-ordinal", "%spellout-ordinal-masculine"]}
numberMarkerList = ["decimal", "decimalZero", "decimalFullWidth", "decimalEnclosedCircle", "lowerLetter", "upperLetter"] + list(numberRomanObject.keys()) + list(numberLocaleObject.keys()) + list(numberCycleObject.keys()) + list(numberSystemObject.keys()) + list(numberTextRuleObject.keys())

symbolPrivateStart = 61440
symbolObject = symbolBuild()

tagChartCategoryList = ["cat", "xVal"]
tagChartValueList = ["val", "yVal"]

characterDrawingObject = {"tab": " ", "br": " "}

valueFalseList = ["0", "false", "off"]
tagControlList = ["dropDownList", "comboBox"]

separatorOption = " / "

messageEncryption = "Encryption not supported."
messagePasswordRequired = "Password required."
messagePasswordWrong = "Password wrong."

textBullet = chr(8226)

markComment = "c"

textOptionMark = "[x]"
textOptionEmpty = "[ ]"
textBlank = "____"

characterPrivate = chr(57344)
characterHyphenSoft = chr(173)
characterHyphenMark = chr(8288)

categoryWordList = ["L", "N"]

blockPresentationList = [icu.UBlockCode.ALPHABETIC_PRESENTATION_FORMS, icu.UBlockCode.VERTICAL_FORMS, icu.UBlockCode.CJK_COMPATIBILITY_FORMS]
blockMathList = [icu.UBlockCode.MATHEMATICAL_ALPHANUMERIC_SYMBOLS]

widthWideList = [icu.Char.getPropertyValueEnum(icu.UProperty.EAST_ASIAN_WIDTH, "W"), icu.Char.getPropertyValueEnum(icu.UProperty.EAST_ASIAN_WIDTH, "F")]
lineBreakComplex = icu.Char.getPropertyValueEnum(icu.UProperty.LINE_BREAK, "SA")
ideographEquivalentObject = ideographEquivalentBuild()
ideographVariantObject = ideographVariantBuild()
ideographExemplarObject = ideographExemplarBuild()

labelTable = "table"
labelImage = "image"
labelText = "text"
labelForm = "form"
labelFormula = "formula"
labelFormulaInline = "formula_inline"
labelCaption = "caption"
labelFootnote = "footnote"
labelHeader = "header"
labelPageList = [labelHeader, "footer"]
labelFloatList = ["caption", "footnote", "image"]
labelGraphicList = ["image", "table"]
labelOptionMark = "checkbox_selected"
labelOptionEmpty = "checkbox_unselected"
labelOptionList = [labelOptionMark, labelOptionEmpty]
labelTitle = "paragraph_title"
labelTitleObject = {"doc_title": 1, labelTitle: 2}

levelTitleMaximum = 6
