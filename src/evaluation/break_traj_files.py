"""Break a traj file into a directory of xyz files."""
from pathlib import Path
from tqdm import tqdm

import numpy as np

from ase.io import write, Trajectory


def order_of_magnitude(number):
    """Get order of magnitude of a number."""
    return int(np.log10(number))


def break_trajectory(traj_path: Path, dirname: str = None):
    """Break trajectory into a directory of xyz files."""
    if isinstance(traj_path, str):
        traj_path = Path(traj_path)
    if dirname is None:
        dir_path = traj_path.parent / traj_path.stem
    else:
        dir_path = traj_path.parent / dirname
    dir_path.mkdir(parents=True, exist_ok=True)
    [p.unlink() for p in dir_path.rglob("*.xyz")]

    traj = Trajectory(filename=traj_path)
    mag = order_of_magnitude(len(traj))
    for i, ats in enumerate(traj):
        write(dir_path / f"{str(i).zfill(mag+1)}.xyz", ats)


if __name__ == "__main__":
    sim_dir = Path("data", "output", "trajectories", "pipeline_test")
    for p in tqdm((sim_dir / "Ce_CO").rglob("*.traj")):
        break_trajectory(p)
