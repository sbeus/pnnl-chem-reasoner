"""Run the sweep over gnn calculated structures."""
import random

from pathlib import Path
from tqdm import tqdm

from ase.io import Trajectory

paths = [p for p in tqdm(Path("/dev/shm/chemreasoner/catalysis").rglob("*/*.traj"))]
choices = []
counter = 0
while len(choices) < 40:
    counter += 1
    print(counter)
    choice = random.choice(paths)
    if choice not in choices:
        ats = Trajectory(str(choice))[-1]
        if ats.get_potential_energy() < 10:
            choices.append(str(choices))
