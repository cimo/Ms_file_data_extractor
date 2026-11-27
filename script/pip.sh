#!/bin/bash

p1=$(printf '%s' "${1}" | xargs)

if [ -z "${p1}" ]
then
    echo -e "\n❌ pip.sh - Missing parameter."

    exit 1
fi

parameter1="${p1}"

pathEnv="${PATH_ROOT}.venv/"

if [ ! -d "${pathEnv}" ]
then
    python3 -m venv --system-site-packages "${pathEnv}"
fi

. "${pathEnv}bin/activate"

python3 -m pip install --no-cache-dir --upgrade pip==26.2.1

python3 -m pip install -r "${PATH_ROOT}requirement.txt"

# Onnx
if [ "${parameter1}" = "gpu" ]
then
    if command -v nvidia-smi > "/dev/null" 2>&1 || [ -c "/dev/nvidiactl" ] || [ -d "/proc/driver/nvidia" ]
    then
        python3 -m pip install onnxruntime-gpu==1.24.4
    elif command -v rocminfo > "/dev/null" 2>&1 || [ -e "/dev/kfd" ] || [ -d "/sys/module/amdgpu" ]
    then
        python3 -m pip install onnxruntime-rocm==1.24.4
    fi
elif [ "${parameter1}" = "cpu" ]
then
    cpuVendor=$(awk -F: '/vendor_id/{gsub(/^[ \t]+/,"",$2); print $2; exit}' "/proc/cpuinfo")

    if [ "${cpuVendor}" = "AuthenticAMD" ]
    then
        python3 -m pip install onnxruntime==1.24.4
    elif [ "${cpuVendor}" = "GenuineIntel" ]
    then
        python3 -m pip install onnxruntime-openvino==1.24.1
    fi
fi

# Onnx
pathModel="/home/app/onnx/model/"
urlModel="https://huggingface.co/cimo001/"

mkdir -p "${pathModel}"

modelList=(
    "paddle/PP-DocLayout_plus-L/onnx/pp-docLayout_plus-l.onnx"
    "paddle/PP-OCRv6_medium_det/onnx/pp-ocrV6_medium_det.onnx"
    "paddle/PP-OCRv6_medium_rec/onnx/pp-ocrV6_medium_rec.onnx"
    "paddle/PP-OCRv6_medium_rec/onnx/dictionary.txt"
    "paddle/RT-DETR-L_wired_table_cell_det/onnx/rt-detr-l_wired_table_cell_det.onnx"
    "paddle/RT-DETR-L_wireless_table_cell_det/onnx/rt-detr-l_wireless_table_cell_det.onnx"
    "paddle/PP-LCNet_x1_0_doc_ori/onnx/pp-lcNet_x1_0_doc_ori.onnx"
    "paddle/PP-FormulaNet_plus-L/onnx/pp-formulaNet_plus-l_encoder.onnx"
    "paddle/PP-FormulaNet_plus-L/onnx/pp-formulaNet_plus-l_decoder.onnx"
    "paddle/PP-FormulaNet_plus-L/onnx/tokenizer.json"
    "docling/Docling-Layout-Heron/onnx/docling-layout-heron.onnx"
    "docling/TableFormer/onnx/tableFormer_encoder.onnx"
    "docling/TableFormer/onnx/tableFormer_decoder.onnx"
    "docling/TableFormer/onnx/tableFormer_box.onnx"
    "microsoft/table-transformer-structure-recognition-v1.1-all/onnx/model.onnx"
    "jhu-clsp/mmBERT-small/onnx/model_mask.onnx"
    "jhu-clsp/mmBERT-small/onnx/tokenizer.json"
    "ndl/PARSeq-tiny/onnx/parseq-tiny_30.onnx"
    "ndl/PARSeq-tiny/onnx/parseq-tiny_50.onnx"
    "ndl/PARSeq-tiny/onnx/parseq-tiny_100.onnx"
    "ndl/PARSeq-tiny/onnx/dictionary.txt"
)

for model in "${modelList[@]}"
do
    pathLocal="${pathModel}${model/\/onnx\///}"

    if [ ! -f "${pathLocal}" ]
    then
        echo "Download onnx: ${pathLocal}"

        mkdir -p "$(dirname "${pathLocal}")"

        if ! curl -fsSL "${urlModel}${model%%/*}/resolve/main/${model#*/}" -o "${pathLocal}"
        then
            echo "Skip onnx - ${pathLocal}: download failed."

            rm -f "${pathLocal}"
        fi
    fi
done
