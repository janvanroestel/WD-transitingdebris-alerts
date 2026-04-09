"""
Parse ZTF forced photometry files and convert to JSON for the website.
Matches ztffps files to objects via coordinate proximity.
"""

import os
import re
import json
import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
import astropy.units as u

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZTFFPS_DIR = os.path.join(BASE_DIR, "ztffps")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "forcedphot")
OBJECTS_CSVS = [
    os.path.join(BASE_DIR, "objects_new.csv"),
    os.path.join(BASE_DIR, "objects_known.csv"),
]


def load_objects():
    """Load all object CSVs and convert coordinates to decimal degrees."""
    dfs = []
    for csv_path in OBJECTS_CSVS:
        if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
            continue
        df = pd.read_csv(csv_path, header=None, comment="%",
                         names=["name", "ztf_id", "ra_sex", "dec_sex", "mag"],
                         usecols=[0, 1, 2, 3, 4])
        df = df.dropna(subset=["name"])
        dfs.append(df)
    if not dfs:
        raise RuntimeError("No object CSV files found")
    df = pd.concat(dfs, ignore_index=True)
    coords = SkyCoord(df["ra_sex"], df["dec_sex"],
                      unit=(u.hourangle, u.deg))
    df["ra_deg"] = coords.ra.deg
    df["dec_deg"] = coords.dec.deg
    return df


def parse_header_coords(filepath):
    """Extract RA/Dec from forced photometry file header."""
    ra, dec = None, None
    with open(filepath, "r") as f:
        for line in f:
            if not line.startswith("#"):
                break
            m = re.search(r"Requested input R\.A\.\s*=\s*([\d.]+)", line)
            if m:
                ra = float(m.group(1))
            m = re.search(r"Requested input Dec\.\s*=\s*([+-]?[\d.]+)", line)
            if m:
                dec = float(m.group(1))
    return ra, dec


def parse_columns(filepath):
    """Extract the column names from the 'Order of columns' header line."""
    with open(filepath, "r") as f:
        for line in f:
            if "Order of columns" in line:
                # next non-comment line has columns
                col_line = next(f)
                cols = [c.strip() for c in col_line.strip().split(",")]
                return cols
    return None


def read_forcedphot(filepath):
    """Read a forced photometry file into a DataFrame."""
    cols = parse_columns(filepath)
    if cols is None:
        raise ValueError(f"Could not parse columns from {filepath}")

    # Normalize first column name
    if cols[0] in ("sindex", "index"):
        cols[0] = "idx"

    # Count header lines to skip (comments + column header line)
    skip = 0
    with open(filepath, "r") as f:
        for line in f:
            skip += 1
            if "Order of columns" in line:
                skip += 1  # skip the column names line too
                break

    # Also skip the trailing '# ' line after column header
    with open(filepath, "r") as f:
        lines = f.readlines()
        while skip < len(lines) and lines[skip].strip().startswith("#"):
            skip += 1

    df = pd.read_csv(filepath, sep=r"\s+", header=None, names=cols,
                     skiprows=skip, na_values=["null"])
    return df


def process_object(fp_file, obj_row):
    """Process a single forced photometry file for one object."""
    df = read_forcedphot(fp_file)

    # Quality filters
    df = df[df["infobitssci"] == 0]
    df = df[df["forcediffimflux"].notna()]
    df = df[df["forcediffimflux"] != -99999.0]
    df = df[df["forcediffimsnr"] != -99999.0]
    # procstatus can be int, float, or string depending on format
    ps = df["procstatus"].astype(str).str.strip()
    df = df[ps.isin(["0", "0.0"])]
    df = df[df["nearestrefmag"].notna()]

    # Compute total magnitude: reference flux + difference flux
    # F_ref in DN: 10^(0.4 * (zpdiff - nearestrefmag))
    f_ref = 10 ** (0.4 * (df["zpdiff"] - df["nearestrefmag"]))
    f_total = f_ref + df["forcediffimflux"]

    # Only keep points where total flux is positive
    mask = f_total > 0
    df = df[mask]
    f_total = f_total[mask]
    f_ref = f_ref[mask]

    df["mag"] = df["zpdiff"] - 2.5 * np.log10(f_total)
    df["mag_unc"] = 1.0857 * df["forcediffimfluxunc"].abs() / f_total

    result = {
        "name": obj_row["name"],
        "ztf_id": obj_row["ztf_id"],
        "ra_deg": obj_row["ra_deg"],
        "dec_deg": obj_row["dec_deg"],
        "ref_mag": float(obj_row["mag"]),
        "jd": df["jd"].tolist(),
        "mag": df["mag"].round(4).tolist(),
        "mag_unc": df["mag_unc"].round(4).tolist(),
        "filter": df["filter"].tolist(),
    }
    return result


def main():
    objects = load_objects()
    obj_coords = SkyCoord(objects["ra_deg"], objects["dec_deg"], unit=u.deg)

    # Match each ztffps file to an object
    fp_files = [os.path.join(ZTFFPS_DIR, f)
                for f in os.listdir(ZTFFPS_DIR) if f.endswith(".txt")]

    matched = {}
    for fp_file in fp_files:
        ra, dec = parse_header_coords(fp_file)
        if ra is None or dec is None:
            print(f"Warning: could not parse coords from {fp_file}, skipping")
            continue
        fp_coord = SkyCoord(ra, dec, unit=u.deg)
        sep = fp_coord.separation(obj_coords)
        idx = sep.argmin()
        if sep[idx].arcsec > 5:
            print(f"Warning: no match within 5\" for {fp_file}, skipping")
            continue
        name = objects.iloc[idx]["name"]
        if name in matched:
            # Keep both files — append to list
            matched[name].append(fp_file)
        else:
            matched[name] = [fp_file]

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for _, obj in objects.iterrows():
        name = obj["name"]
        if name not in matched:
            print(f"Warning: no forced photometry file for {name}")
            continue

        # If multiple files match, concatenate them
        all_data = []
        for fp_file in matched[name]:
            data = process_object(fp_file, obj)
            all_data.append(data)

        if len(all_data) == 1:
            result = all_data[0]
        else:
            # Merge multiple files
            result = all_data[0].copy()
            for d in all_data[1:]:
                result["jd"].extend(d["jd"])
                result["mag"].extend(d["mag"])
                result["mag_unc"].extend(d["mag_unc"])
                result["filter"].extend(d["filter"])

        outpath = os.path.join(OUTPUT_DIR, f"{name}.json")
        with open(outpath, "w") as f:
            json.dump(result, f)
        print(f"Wrote {outpath} ({len(result['jd'])} points)")


if __name__ == "__main__":
    main()
