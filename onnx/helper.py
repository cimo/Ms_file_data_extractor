import os
import re
import cv2
import icu
import json
import numpy
import hashlib
import unicodedata

stderrFileDescriptor = os.dup(2)
nullFileDescriptor = os.open(os.devnull, os.O_WRONLY)

os.dup2(nullFileDescriptor, 2)

import onnxruntime

os.dup2(stderrFileDescriptor, 2)

os.close(nullFileDescriptor)
os.close(stderrFileDescriptor)

def onnxSessionBuild(pathModel):
    option = onnxruntime.SessionOptions()

    option.log_severity_level = 3

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

    providerAvailableList = onnxruntime.get_available_providers()

    providerList = [provider for provider in providerPreferredList if provider in providerAvailableList]

    inference = onnxruntime.InferenceSession(pathModel, sess_options=option, providers=providerList)

    print(f"Provider available: {providerAvailableList}")
    print(f"Provider active: {inference.get_providers()}\n")

    return inference

# Custom
def tensorNormalize(image, meanList, standardList):
    tensor = (image.astype(numpy.float32) / 255.0 - meanList) / standardList

    return numpy.expand_dims(tensor.transpose((2, 0, 1)), axis=0).astype(numpy.float32)

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

def categoryContainCheck(text, categoryList):
    for a in range(len(text)):
        category = unicodedata.category(text[a])

        if category in categoryList or category[0] in categoryList:
            return True

    return False

def categoryRemove(text, categoryList):
    result = ""

    for a in range(len(text)):
        category = unicodedata.category(text[a])

        if category not in categoryList and category[0] not in categoryList:
            result += text[a]

    return result

def spacelessCheck(character):
    if wideCheck(character):
        return True

    return icu.Char.getIntPropertyValue(character, icu.UProperty.LINE_BREAK) == lineBreakComplex

def whitespaceCheck(character):
    if character == "":
        return False

    return icu.Char.isUWhiteSpace(character)

def privateUseCheck(character):
    if character == "":
        return False

    return icu.Char.charType(character) == icu.UCharCategory.PRIVATE_USE_CHAR

def characterNormalize(text):
    result = ""

    for a in range(len(text)):
        if icu.Char.getIntPropertyValue(text[a], icu.UProperty.BLOCK) == icu.UBlockCode.ALPHABETIC_PRESENTATION_FORMS:
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

    with open(f"{os.path.dirname(__file__)}/language/equivalent.txt", encoding="utf-8") as file:
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

    with open(f"{os.path.dirname(__file__)}/language/variant.txt", encoding="utf-8") as file:
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

def tokenFirstLength(text):
    breakIterator = icu.BreakIterator.createLineInstance(icu.Locale.getRoot())

    breakIterator.setText(text)

    return breakIterator.following(0)

def textNormalize(text):
    result = ""

    textNormalized = icu.Normalizer2.getNFKCCasefoldInstance().normalize(text)

    for a in range(len(textNormalized)):
        if icu.Char.isUWhiteSpace(textNormalized[a]) or icu.Char.hasBinaryProperty(textNormalized[a], icu.UProperty.DEFAULT_IGNORABLE_CODE_POINT):
            continue

        result += textNormalized[a]

    return result

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

def sentenceEndCheck(text):
    textClean = sentenceTailStrip(text)

    return len(textClean) > 0 and icu.Char.hasBinaryProperty(textClean[-1:], icu.UProperty.S_TERM)

def sentenceTailStrip(text):
    result = text.strip()

    while len(result) > 0:
        character = result[-1:]

        if icu.Char.charType(character) == icu.UCharCategory.END_PUNCTUATION:
            indexOpen = groupOpenIndex(result)

            result = result[0:indexOpen] if indexOpen >= 0 else result[0:-1]

            continue

        if icu.Char.charType(character) == icu.UCharCategory.FINAL_PUNCTUATION or icu.Char.hasBinaryProperty(character, icu.UProperty.QUOTATION_MARK) or icu.Char.isUWhiteSpace(character):
            result = result[0:-1]

            continue

        break

    return result

def groupOpenIndex(text):
    for a in range(len(text) - 2, len(text) - 2 - levelReferenceLength, -1):
        if a < 0:
            break

        character = text[a]

        if icu.Char.charType(character) == icu.UCharCategory.START_PUNCTUATION:
            return a

        if icu.Char.charType(character) == icu.UCharCategory.END_PUNCTUATION or icu.Char.hasBinaryProperty(character, icu.UProperty.S_TERM):
            break

    return -1

def boxFromPointList(pointList):
    xList = []
    yList = []

    for a in range(len(pointList)):
        xList.append(pointList[a][0])
        yList.append(pointList[a][1])

    return [min(xList), min(yList), max(xList), max(yList)]

def boxExpand(bboxList, bboxOtherList):
    return [
        min(bboxList[0], bboxOtherList[0]),
        min(bboxList[1], bboxOtherList[1]),
        max(bboxList[2], bboxOtherList[2]),
        max(bboxList[3], bboxOtherList[3])
    ]

def boxSizeMedian(bboxList):
    sizeList = []

    for a in range(len(bboxList)):
        sizeList.append(min(bboxList[a][2] - bboxList[a][0], bboxList[a][3] - bboxList[a][1]))

    sizeList.sort()

    return sizeList[int(len(sizeList) / 2)] if len(sizeList) > 0 else 1

def detectionBoxBuild(detectionList):
    resultList = []

    for a in range(len(detectionList)):
        resultList.append(boxFromPointList(detectionList[a]["coordinate"]))

    return resultList

def textCutCheck(bboxList, bboxCellList):
    if min(bboxList[3], bboxCellList[3]) - max(bboxList[1], bboxCellList[1]) < (bboxList[3] - bboxList[1]) * levelCutOverlap:
        return False

    margin = (bboxList[2] - bboxList[0]) * levelCutMargin

    for a in range(2):
        edge = bboxCellList[a * 2]

        if edge > bboxList[0] + margin and edge < bboxList[2] - margin:
            return True

    return False

def columnGroupAppend(columnList, index, bboxList, itemObject):
    if index < 0:
        columnList.append({"x1": bboxList[0], "x2": bboxList[2], "itemList": [itemObject]})

        return

    columnList[index]["x1"] = min(columnList[index]["x1"], bboxList[0])
    columnList[index]["x2"] = max(columnList[index]["x2"], bboxList[2])

    columnList[index]["itemList"].append(itemObject)

def centerPointCalculate(bboxList):
    return {
        "x": int(round((bboxList[0] + bboxList[2]) / 2)),
        "y": int(round((bboxList[1] + bboxList[3]) / 2))
    }

def sizeDominantCalculate(itemList):
    countObject = {}

    for a in range(len(itemList)):
        if "fontSize" not in itemList[a]:
            continue

        countObject[itemList[a]["fontSize"]] = countObject.get(itemList[a]["fontSize"], 0) + len(itemList[a]["text"])

    result = 0
    countBest = 0

    for size in countObject:
        if countObject[size] > countBest:
            result = size
            countBest = countObject[size]

    return result

def boxCenterInsideCheck(bboxList, boxOuterList):
    centerX = (bboxList[0] + bboxList[2]) / 2
    centerY = (bboxList[1] + bboxList[3]) / 2

    return centerX >= boxOuterList[0] and centerX <= boxOuterList[2] and centerY >= boxOuterList[1] and centerY <= boxOuterList[3]

def rangeOverlapRatio(start, end, startOther, endOther):
    startOverlap = max(start, startOther)
    endOverlap = min(end, endOther)

    if endOverlap <= startOverlap:
        return 0.0

    return (endOverlap - startOverlap) / float(min(end - start, endOther - startOther))

def flowGapCalculate(bboxPreviousList, bboxList, directionObject):
    if directionObject["isVertical"]:
        return {
            "gap": bboxList[1] - bboxPreviousList[3],
            "size": min(bboxPreviousList[2] - bboxPreviousList[0], bboxList[2] - bboxList[0])
        }

    return {
        "gap": bboxPreviousList[0] - bboxList[2] if directionObject["isRightToLeft"] else bboxList[0] - bboxPreviousList[2],
        "size": min(bboxPreviousList[3] - bboxPreviousList[1], bboxList[3] - bboxList[1])
    }

def boxIntersection(bboxList, bboxOtherList):
    x1 = max(bboxList[0], bboxOtherList[0])
    y1 = max(bboxList[1], bboxOtherList[1])
    x2 = min(bboxList[2], bboxOtherList[2])
    y2 = min(bboxList[3], bboxOtherList[3])

    if x2 <= x1 or y2 <= y1:
        return 0

    return (x2 - x1) * (y2 - y1)

def boxArea(bboxList):
    return (bboxList[2] - bboxList[0]) * (bboxList[3] - bboxList[1])

def boxIou(bboxList, bboxOtherList):
    areaIntersection = boxIntersection(bboxList, bboxOtherList)

    if areaIntersection == 0:
        return 0.0

    return areaIntersection / float(boxArea(bboxList) + boxArea(bboxOtherList) - areaIntersection)

def boxContainedRemove(boxList, nameKey):
    resultList = []

    for a in range(len(boxList)):
        area = boxArea(boxList[a][nameKey])

        isContained = False

        for b in range(len(boxList)):
            if a == b:
                continue

            if boxArea(boxList[b][nameKey]) <= area:
                continue

            if boxIntersection(boxList[a][nameKey], boxList[b][nameKey]) / float(area) >= levelBoxContained:
                isContained = True

                break

        if isContained == False:
            resultList.append(boxList[a])

    return resultList

def imageInkBuild(image):
    return cv2.threshold(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

def mediaImageWrite(image, pathOutput):
    imageHeight, imageWidth = image.shape[0:2]

    sideLongest = max(imageHeight, imageWidth)

    if sideLongest > mediaSideMax:
        ratio = mediaSideMax / sideLongest

        image = cv2.resize(image, (int(round(imageWidth * ratio)), int(round(imageHeight * ratio))), interpolation=cv2.INTER_AREA)

    isEncode, bufferEncode = cv2.imencode(".webp", image, [cv2.IMWRITE_WEBP_QUALITY, mediaQuality])

    if not isEncode:
        return ""

    byteList = bufferEncode.tobytes()

    fileName = f"{hashlib.md5(byteList).hexdigest()}.webp"

    pathMedia = f"{pathOutput}media/{fileName}"

    if not os.path.exists(pathMedia):
        os.makedirs(f"{pathOutput}media/", exist_ok=True)

        with open(pathMedia, "wb") as file:
            file.write(byteList)

    return f"media/{fileName}"

def astWrite(pathOutput, astPageList):
    with open(f"{pathOutput}debug/layout/ast.json", "w", encoding="utf-8") as file:
        json.dump({"pageList": astPageList}, file, ensure_ascii=False, indent=4)

def boxDebugWrite(image, bboxList, pathFile):
    imageDebug = image.copy()

    for a in range(len(bboxList)):
        cv2.rectangle(imageDebug, (bboxList[a][0], bboxList[a][1]), (bboxList[a][2], bboxList[a][3]), (0, 200, 0), 1)

    cv2.imwrite(pathFile, imageDebug)

mediaSideMax = 1280
mediaQuality = 80

levelSpaceChar = 1.0
levelSpaceWord = 0.5
levelSpaceGap = 0.15
levelBoxContained = 0.9
levelBoxNms = 0.5
levelVerticalRatio = 2.0
levelColumnOverlap = 0.5
levelLineDouble = 1.7
levelRuleLength = 1.5
levelTitleSize = 1.15
levelTitleLength = 120
levelReferenceLength = 20
levelCutOverlap = 0.5
levelCutMargin = 0.15

textOptionMark = "[x]"
textOptionEmpty = "[ ]"
textBullet = "- "

separatorOption = " / "

categoryLetterList = ["L"]
categoryOperatorList = ["Sm", "Pd"]
categoryCasedList = ["Lu", "Ll", "Lt"]
categoryWordList = ["L", "Nd"]
categoryBlankList = ["Zs", "Cc"]
categorySkeletonList = ["Nd", "Z", "Cc"]

widthWideList = [icu.Char.getPropertyValueEnum(icu.UProperty.EAST_ASIAN_WIDTH, "W"), icu.Char.getPropertyValueEnum(icu.UProperty.EAST_ASIAN_WIDTH, "F")]
lineBreakComplex = icu.Char.getPropertyValueEnum(icu.UProperty.LINE_BREAK, "SA")
ideographEquivalentObject = ideographEquivalentBuild()
ideographVariantObject = ideographVariantBuild()
ideographExemplarObject = ideographExemplarBuild()
# Custom
