"""Not sure if this should go in here or not."""
import pickle
import random

from pathlib import Path
from typing import Union

from ase import Atoms
from ase.io import write
import ase.build as build
from ase.data import reference_states, atomic_numbers

import numpy as np


with open(Path("data", "input_data", "oc", "oc_20_adsorbates.pkl"), "rb") as f:
    oc_20_ads_structures = pickle.load(f)
    oc_20_ads_structures = {
        v[1]: (v[0], v[2:]) for k, v in oc_20_ads_structures.items()
    }

organized_structures = {"fcc": [], "bcc": [], "hcp": []}
for symbol, z in atomic_numbers.items():
    if reference_states[z] is not None:
        symmetry = reference_states[z]["symmetry"]
        if symmetry in ["fcc", "bcc", "hcp"]:
            organized_structures[symmetry].append(symbol)

for k, v in organized_structures.items():
    print(f"{k}:\t{v}")


class StructureGenerationError(Exception):
    """Error class for structure generation."""

    def __init__(self, message):
        """Create a structure generation error."""
        super().__init__(message)


class AdsorbatePlacementError(Exception):
    """Error class for structure generation."""

    def __init__(self, message):
        """Create an adsorbate binding error."""
        super().__init__(message)


def save_xyz(fname: Path, atoms: Atoms):
    """Save atoms object to xyz file."""
    write(fname, atoms)


def create_bulk(name):
    """Create a bulk from the name."""
    Z = atomic_numbers[name]

    ref = reference_states[Z]
    symmetry = ref["symmetry"]

    if symmetry == "fcc":
        ats = build.fcc111(name, (4, 4, 4))
    elif symmetry == "bcc":
        ats = build.bcc110(name, (4, 4, 4))
    elif symmetry == "hcp":
        ats = build.hcp0001(name, (4, 4, 4))

    return ats

    # try:
    #     ats = build.fcc111(name, size=(4, 4, 4), orthogonal=True)
    # except Exception as err:
    #     if str(err) == f"Can't guess lattice constant for fcc-{name}!":
    #         ats = build.bcc100(name, size=(4, 4, 4), orthogonal=True)
    #     else:
    #         raise err
    # return ats


def generate_bulk_ads_pairs(
    bulk: Atoms,
    ads: str,
    sites: Union[str, list[str]] = None,
    height=3.0,
) -> Union[Atoms, list[Atoms]]:
    """Add adsorbate to a bulk in the given locations."""
    return_value = False
    if sites is None:
        sites = list(bulk.info["adsorbate_info"]["sites"].keys())
    elif isinstance(sites, str):
        return_value = True
        sites = [sites]

    bulk_ads_pairs = []
    for s in sites:
        num_tries = 0
        valid = False  # Indicate whether generated structure is valid
        while not valid:
            new_bulk = bulk.copy()
            new_ads = ads.copy()
            # randomly select the binding location
            site_name = random.choice(list(new_bulk.info["adsorbate_info"]["sites"]))
            position = new_bulk.info["adsorbate_info"]["sites"][site_name]
            # randomly set the binding atom
            bulk_z = list(set(bulk.get_atomic_numbers()))
            binding_z = bulk_z[np.random.choice(len(bulk_z))]
            binding_idx = get_top_atom_index(new_bulk, position)
            numbers = new_bulk.get_atomic_numbers()
            numbers[binding_idx] = binding_z
            new_bulk.set_atomic_numbers(numbers)
            # randomly sample rotation angles
            z_rot = random.uniform(0, 360)
            x_rot = random.uniform(0, 15)
            y_rot = random.uniform(0, 15)
            # Do in-plane rotations first
            new_ads.rotate("z", z_rot)
            new_ads.rotate("x", x_rot)
            new_ads.rotate("y", y_rot)
            # Apply adsorbate to new_bullk
            new_bulk = combine_adsorbate_slab(
                new_bulk,
                new_ads,
                height=height + 0.1 * num_tries,
                position=position,
            )
            new_bulk.center(vacuum=13.0, axis=2)
            ads_mask = np.argwhere(new_bulk.get_tags() == 0)
            distance_matrix = new_bulk.get_all_distances(mic=True)
            if all(
                distance_matrix[ads_mask, ~ads_mask] > 0.1
            ):  # Check adsorbate distance to slab
                valid = True

            else:
                num_tries += 1
        bulk_ads_pairs.append(new_bulk)
    if return_value:
        return bulk_ads_pairs[0]
    else:
        return bulk_ads_pairs


def combine_adsorbate_slab(slab: Atoms, ads: Atoms, height=3, position=None) -> Atoms:
    """Attach an adsorbate to a slab adsorption site."""
    slab = slab.copy()
    ads = ads.copy()
    if position is None:
        position = random.choice(list(slab.info["adsorbate_info"]["sites"]))
        coords = slab.info["adsorbate_info"]["sites"][position]

    binding_molecules = ads.info.get("binding_sites", np.array([0]))

    if len(binding_molecules) == 2:
        disp = -np.diff(ads.get_positions()[binding_molecules])
        coords -= disp[0:2] / 2  # displace position in the xy-plane
    elif len(binding_molecules) != 1:
        raise AdsorbatePlacementError(
            f"Unable to add adsorbate with {len(binding_molecules)} binding molecules."
        )
    build.add_adsorbate(slab, ads, 3, position=coords, mol_index=binding_molecules[0])
    return slab


def get_top_atom_index(slab: Atoms, position) -> int:
    """Get the index of the adsorbate binding location on the slab.

    The code to get the z corrdinate from:
    https://wiki.fysik.dtu.dk/ase/_modules/ase/build/surface.html#add_adsorbate."""
    # start of code from ase
    info = slab.info.get("adsorbate_info", {})
    # Get the z-coordinate:
    if "top layer atom index" in info:
        a = info["top layer atom index"]
    else:
        a = slab.positions[:, 2].argmax()
        if "adsorbate_info" not in slab.info:
            slab.info["adsorbate_info"] = {}
        slab.info["adsorbate_info"]["top layer atom index"] = a
    # end of code from ase
    z = slab.positions[a, 2]

    coords = np.array(list(position) + [z])
    distances = np.linalg.norm(slab.get_positions() - coords, axis=1)
    min_idx = np.argmin(distances)  # get the closes atom

    return min_idx


def convert_alloy(bulk, other_symbols=Union[str, list[str]]):
    """Convert an existing metal to a metal alloy."""
    if isinstance(other_symbols, str):
        other_symbols = [other_symbols]

    bulk = bulk.copy()

    ind = list(range(len(bulk)))
    random.shuffle(ind)
    alloy_partition = len(bulk) // 3
    old_z = bulk.get_atomic_numbers()
    new_z = [0] * len(bulk)
    for i, idx in enumerate(ind):
        elem = i // alloy_partition
        if elem < len(other_symbols):
            new_z[idx] = atomic_numbers[other_symbols[elem]]
        else:
            new_z[idx] = old_z[idx]
    bulk.set_atomic_numbers(new_z)
    return bulk


def llm_answer_to_symbols(
    answer=Union[str, list[str]], model="gpt-3.5-turbo"
) -> list[Union[str, None]]:
    """Turn an llm answer into a list of atomic symbols or None if not possible."""
    from llm.query import run_query  # noqa: E402

    return_value = False
    if isinstance(answer, str):
        answer = [answer]
        return_value = True

    print(answer)

    example_format = ""
    for i, ans in enumerate(answer):
        example_format += f"{ans}: [list_{i}]\n"

    answer_string = ", ".join(answer)
    prompt = (
        f"Consider the following list of catalysts:\n{answer_string}.\n\n"
        "For each catalyst, return the list of chemical symbols that make up the "
        "catalyst. If a catalyst does not have a chemical symbol, return None. "
        "If a catalyst is already a chemical formula, repeat the elements in the "
        "chemical formula.\n\n"
        "Format your list as:\n"
        f"{example_format}"
    )

    answer_parsed = run_query(
        query=prompt, model=model, **{"temperature": 0.0, "top_p": 0}
    )
    answer_list_parsed = [None] * len(answer)
    for line in answer_parsed.split("\n"):
        if ":" in line:
            cat, syms = line.split(":")
            idx = answer.index(cat)  # ensure ording is preserved
            syms_list = list(
                {s.strip() for s in syms.strip().strip("[").strip("]").split(",")}
            )  # Use a set for unique elements only
            if syms_list == ["None"]:
                syms_list = None
            answer_list_parsed[idx] = syms_list

    if return_value:
        return answer_list_parsed[0]
    else:
        return answer_list_parsed


def symbols_list_to_bulk(symbols_list):
    """Return a bulk from a list of symbols that constructs it."""
    try:
        bulk = create_bulk(symbols_list[0])
    except Exception:
        raise StructureGenerationError(
            f"Unable to create a bulk for the element {symbols_list[0]}.",
        )
    if len(symbols_list) > 1 and len(symbols_list) < 4:
        for sym in symbols_list[1:]:
            try:
                bulk = convert_alloy(bulk, sym)
            except Exception:
                raise StructureGenerationError(
                    f"Unable to incorporate element {sym} into alloy.",
                )
    bulk.info.update({"bulk_syms": symbols_list})
    return bulk


def ads_symbols_to_structure(syms: str):
    """Turn adsorbate symbols to a list of strings."""
    if "*" in syms:
        ats = oc_20_ads_structures[syms][0].copy()
        ats.info.update({"binding_molecules": oc_20_ads_structures[syms][1][0].copy()})

    elif syms in map(lambda s: s.replace("*", ""), oc_20_ads_structures.keys()):
        idx = list(
            map(lambda s: s.replace("*", ""), oc_20_ads_structures.keys())
        ).index(syms)
        given_syms = syms
        syms = list(oc_20_ads_structures.keys())[idx]
        ats = oc_20_ads_structures[syms][0].copy()
        ats.info.update({"given_syms": given_syms})
        ats.info.update(
            {"binding_molecules": oc_20_ads_structures[syms][1][0].copy()}
        )  # get binding indices

    else:
        ats = build.molecule(syms)
    ats.info.update({"syms": syms})

    return ats


if __name__ == "__main__":
    # print(reference_states)
    # ads = Atoms("CO", positions=[[0, 0, 0], [1.12, 0, 0]])
    pt = create_bulk("Pt")
    print(pt.info)
    # pt = add_adsorbates(ads, pt, "on-top")
    # print(pt.info)
    # save_xyz("fcc.xyz", pt)

    # fe = create_bulk("Fe")
    # fe = add_adsorbates(ads, fe, "on-top")
    # print(fe)
    # save_xyz("bcc.xyz", fe)

    # print(fe.info["adsorbate_info"])

    # ti = create_bulk("Ti")
    # ti = add_adsorbates(ads, ti, "on-top")
    # print(ti)
    # save_xyz("hcp.xyz", ti)

    # # make an alloy
    # pt = create_bulk("Pt")
    # ptni = convert_alloy(pt, ["Ni"])
    # print(ptni)
    # save_xyz("ptni.xyz", ptni)

    # print(
    #     llm_answer_to_symbols(
    #         [
    #             "Nickel",
    #             "Clay",
    #             "Cobalt oxide",
    #             "Zeolites",
    #             "CuO2",
    #             "Platinum-doped nickel",
    #             "Nickel-based catalysts",
    #             "NiMnCu",
    #         ]
    #     )
    # )
    # print("\n\n")
    # ads = ads_symbols_to_structure("CO2")
    # ads = ads_symbols_to_structure("CO")
    # print(ads)
    # print(ads.info)
    # print(ads.get_atomic_numbers())
    # print(ads.get_positions())

    # adslab = combine_adsorbate_slab(pt, ads)
    # print(adslab)
    # print(adslab.get_tags())
    # print(adslab.get_atomic_numbers())
