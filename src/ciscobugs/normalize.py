"""Name the hardware: families from the notes, models from the text.

Cisco publishes one note per product series, or per group of series: the family of a
bug is the family of the notes that list it, which is reliable. A model is only
known when the headline names it, and a mention means "the headline cites it",
never "only this model is affected".
"""
import re
from typing import Dict, List, Optional, Set

# (pattern, family): the first that matches names the family of a model.
MODEL_FAMILIES = [
    (r"N9K-[A-Z0-9][A-Z0-9-]*[A-Z0-9]", "Nexus 9000"),
    (r"N3K-[A-Z0-9][A-Z0-9-]*[A-Z0-9]", "Nexus 3000"),
    (r"N7K-[A-Z0-9][A-Z0-9-]*[A-Z0-9]", "Nexus 7000"),
    (r"C92\d{2}[A-Z]{0,2}", "Catalyst 9200"),
    (r"C93\d{2}[A-Z]{0,2}", "Catalyst 9300"),
    (r"C94\d{2}[A-Z]{0,2}", "Catalyst 9400"),
    (r"C95\d{2}[A-Z]{0,2}", "Catalyst 9500"),
    (r"C96\d{2}[A-Z]{0,2}", "Catalyst 9600"),
    (r"C82\d{2}[A-Z]{0,2}", "Catalyst 8200"),
    (r"C83\d{2}[A-Z]{0,2}", "Catalyst 8300"),
    (r"C85\d{2}[A-Z]{0,2}", "Catalyst 8500"),
    (r"C8000V", "Catalyst 8000V"),
    (r"C11\d{2}[A-Z]{0,3}", "ISR 1000"),
    (r"ISR ?11\d{2}[A-Z]{0,3}", "ISR 1000"),
    (r"ISR ?4[2-4]\d{2}", "ISR 4000"),
    (r"ASR ?-?920", "ASR 920"),
    (r"ASR ?-?10\d{2}(?:-[A-Z0-9]+)?", "ASR 1000"),
    (r"ASR ?-?9\d{3}", "ASR 9000"),
    (r"NCS ?-?55[A-Z0-9]{1,3}", "NCS 5500"),
    (r"N540X?(?:-[A-Z0-9]+)?|NCS ?-?540", "NCS 540"),
    (r"NCS ?-?560(?:-\d)?", "NCS 560"),
    (r"WS-C3850", "Catalyst 3850"),
    (r"WS-C2960XR?", "Catalyst 2960-X"),
    (r"C1000(?:FE)?-\d+[A-Z]*", "Catalyst 1000"),
]
MODEL = re.compile(r"(?<![\w-])(" + "|".join(f"(?:{p})" for p, _ in MODEL_FAMILIES) + r")(?![\w])")
COMPILED = [(re.compile(rf"^(?:{p})$"), family) for p, family in MODEL_FAMILIES]
FIREWALL_MODEL = re.compile(r"(?<![\w-])(FPR ?-?\d{4}|ASA ?55\d{2}(?:-X)?|ASAv|FTDv|Secure Firewall \d{4})(?![\w])", re.I)

FAMILY_MENTIONS = [
    (r"\bNexus ?9[0-9]{3}|\bN9K\b|\bNexus 9000", "Nexus 9000"),
    (r"\bNexus ?3[0-9]{3}|\bN3K\b|\bNexus 3000", "Nexus 3000"),
    (r"\bNexus ?7[0-9]{3}|\bN7K\b|\bNexus 7000", "Nexus 7000"),
    (r"\bCat(?:alyst)? ?92\d{2}|\bC92\d{2}", "Catalyst 9200"),
    (r"\bCat(?:alyst)? ?93\d{2}|\bC93\d{2}", "Catalyst 9300"),
    (r"\bCat(?:alyst)? ?94\d{2}|\bC94\d{2}", "Catalyst 9400"),
    (r"\bCat(?:alyst)? ?95\d{2}|\bC95\d{2}", "Catalyst 9500"),
    (r"\bCat(?:alyst)? ?96\d{2}|\bC96\d{2}", "Catalyst 9600"),
    (r"\bC8200|\bCatalyst 8200", "Catalyst 8200"),
    (r"\bC8300|\bCatalyst 8300", "Catalyst 8300"),
    (r"\bC8500|\bCatalyst 8500", "Catalyst 8500"),
    (r"\bC8000V|\bCatalyst 8000V", "Catalyst 8000V"),
    (r"\bISR ?1[01]\d{2}|\bISR1K\b", "ISR 1000"),
    (r"\bISR ?4[2-4]\d{2}|\bISR4K\b", "ISR 4000"),
    (r"\bASR ?-?920", "ASR 920"),
    (r"\bASR ?-?1\d{3}|\bASR1K\b", "ASR 1000"),
    (r"\bASR ?-?9\d{3}|\bASR9K\b", "ASR 9000"),
    (r"\bNCS ?-?55", "NCS 5500"),
    (r"\bNCS ?-?540|\bN540", "NCS 540"),
    (r"\bNCS ?-?560", "NCS 560"),
]
FAMILY_PATTERNS = [(re.compile(p, re.I), family) for p, family in FAMILY_MENTIONS]


def canonical_model(text: str) -> str:
    return re.sub(r"\s+", "", text).upper().replace("ASR-", "ASR").replace("NCS-", "NCS")


def family_of_model(model: str, system: Optional[str] = None) -> Optional[str]:
    if system == "asa" and FIREWALL_MODEL.fullmatch(model):
        return "Secure Firewall ASA"
    if system == "ftd" and FIREWALL_MODEL.fullmatch(model):
        return "Secure Firewall Threat Defense"
    for pattern, family in COMPILED:
        if pattern.match(model):
            return family
    return None


def models_in(text: str, system: Optional[str] = None) -> List[str]:
    found: Set[str] = {canonical_model(m) for m in MODEL.findall(text)}
    if system in ("asa", "ftd"):
        found |= {canonical_model(m).replace("SECUREFIREWALL", "SECURE FIREWALL ") for m in FIREWALL_MODEL.findall(text)}
    return sorted(m for m in found if family_of_model(m, system))


def families_in(text: str) -> List[str]:
    return sorted({family for pattern, family in FAMILY_PATTERNS if pattern.search(text)})


def model_sort_key(model: str):
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", model)]


def model_families(models: List[str], system: str) -> Dict[str, str]:
    return {model: family_of_model(model, system) for model in models}
