"""Human-friendly labels shared by tools and renders."""

GOT_LOCATIONS = (
    "Winterfell",
    "King's Landing",
    "Dragonstone",
    "The Wall",
    "Castle Black",
    "Oldtown",
    "Highgarden",
    "Casterly Rock",
    "Riverrun",
    "The Eyrie",
    "Storm's End",
    "Sunspear",
    "Pyke",
    "Harrenhal",
    "Moat Cailin",
    "White Harbor",
    "The Twins",
    "Bear Island",
    "Dreadfort",
    "Karhold",
    "Last Hearth",
    "Greywater Watch",
    "Tarth",
    "Lannisport",
    "Qarth",
    "Braavos",
    "Meereen",
    "Vaes Dothrak",
    "Hardhome",
    "Craster's Keep",
)


def substation_label(sub_id, degree=0, incident_rho=0.0):
    location = GOT_LOCATIONS[(int(sub_id) * 7) % len(GOT_LOCATIONS)]
    role = substation_role(degree, incident_rho)
    return f"{location} {role} UW {int(sub_id)}"


def substation_role(degree=0, incident_rho=0.0):
    if degree >= 5 or incident_rho >= 1.0:
        return "Hub"
    if degree >= 3 or incident_rho >= 0.85:
        return "Tie"
    if degree <= 1:
        return "Stub"
    return "Chain"


def line_label(line_id, from_label, to_label):
    return f"Line {int(line_id)}: {from_label} -> {to_label}"
