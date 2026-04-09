"""
Fetch ZTF alerts from Kowalski for each target object.
Auth via env vars (KOWALSKI_USERNAME, KOWALSKI_PASSWORD, KOWALSKI_HOST)
or fall back to local secrets file.
"""

import os
import json
import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
import astropy.units as u
from penquins import Kowalski

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBJECTS_CSVS = [
    os.path.join(BASE_DIR, "objects_new.csv"),
    os.path.join(BASE_DIR, "objects_known.csv"),
]
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "alerts")

FID_TO_FILTER = {1: "ZTF_g", 2: "ZTF_r", 3: "ZTF_i"}

PROJECTION = {
    "objectId": 1,
    "candidate.ra": 1,
    "candidate.dec": 1,
    "candidate.jd": 1,
    "candidate.magpsf": 1,
    "candidate.sigmapsf": 1,
    "candidate.magnr": 1,
    "candidate.sigmagnr": 1,
    "candidate.isdiffpos": 1,
    "candidate.fid": 1,
    "candidate.programid": 1,
    "candidate.rb": 1,
    "candidate.drb": 1,
}


def get_kowalski_connection():
    """Connect to Kowalski using env vars or local secrets file."""
    username = os.environ.get("KOWALSKI_USERNAME")
    password = os.environ.get("KOWALSKI_PASSWORD")
    host = os.environ.get("KOWALSKI_HOST")

    if username and password:
        kwargs = {"username": username, "password": password}
        if host:
            kwargs["host"] = host
        return Kowalski(**kwargs, verbose=False, timeout=300)

    # Fall back to local secrets
    secrets_path = os.path.expanduser("~/mysecrets/secrets.json")
    if os.path.exists(secrets_path):
        with open(secrets_path) as f:
            secrets = json.load(f)
        return Kowalski(**secrets["kowalski"], verbose=False, timeout=300)

    raise RuntimeError(
        "No Kowalski credentials found. Set KOWALSKI_USERNAME/KOWALSKI_PASSWORD "
        "env vars or create ~/mysecrets/secrets.json"
    )


def load_objects():
    """Load all object CSVs with decimal degree coordinates."""
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


def make_query(ra, dec, radius=3.0):
    """Build a Kowalski cone search query for a single object."""
    return {
        "query_type": "cone_search",
        "query": {
            "object_coordinates": {
                "radec": {"target": (ra, dec)},
                "cone_search_radius": f"{radius:.2f}",
                "cone_search_unit": "arcsec",
            },
            "catalogs": {
                "ZTF_alerts": {
                    "filter": {},
                    "projection": PROJECTION,
                }
            },
        },
    }


def extract_alerts(response, query_key="target"):
    """Extract alert data from Kowalski response."""
    try:
        alerts = response["default"]["ZTF_alerts"][query_key]
    except (KeyError, TypeError):
        # Try alternative response structures
        try:
            data = response.get("data", response)
            alerts = data["ZTF_alerts"][query_key]
        except (KeyError, TypeError):
            return []
    return alerts if isinstance(alerts, list) else []


def main():
    objects = load_objects()
    k = get_kowalski_connection()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for _, obj in objects.iterrows():
        name = obj["name"]
        ztf_id = obj["ztf_id"]
        has_ztf_id = ztf_id and ztf_id != "-"
        file_key = ztf_id if has_ztf_id else name
        ra = obj["ra_deg"]
        dec = obj["dec_deg"]

        q = make_query(ra, dec)
        response = k.query(q)

        # Debug: print response structure for first object
        if _ == 0:
            print(f"DEBUG response type: {type(response)}")
            if isinstance(response, dict):
                print(f"DEBUG response keys: {list(response.keys())}")
                for k1, v1 in response.items():
                    if isinstance(v1, dict):
                        print(f"DEBUG response['{k1}'] keys: {list(v1.keys())}")
                        for k2, v2 in v1.items():
                            if isinstance(v2, dict):
                                print(f"DEBUG response['{k1}']['{k2}'] keys: {list(v2.keys())}")
                                for k3, v3 in v2.items():
                                    if isinstance(v3, (list, dict)):
                                        print(f"DEBUG response['{k1}']['{k2}']['{k3}'] type={type(v3).__name__} len={len(v3)}")
                                    else:
                                        print(f"DEBUG response['{k1}']['{k2}']['{k3}'] = {v3}")
            else:
                print(f"DEBUG response (first 500 chars): {str(response)[:500]}")

        alerts = extract_alerts(response)

        jd_list = []
        mag_list = []
        mag_unc_list = []
        filter_list = []
        objid_list = []

        for alert in alerts:
            cand = alert.get("candidate", alert)
            fid = cand.get("fid")
            filt = FID_TO_FILTER.get(fid, f"unknown_{fid}")
            magpsf = cand.get("magpsf")
            sigmapsf = cand.get("sigmapsf")
            magnr = cand.get("magnr")
            sigmagnr = cand.get("sigmagnr")
            isdiffpos = cand.get("isdiffpos")
            jd = cand.get("jd")

            if magpsf is None or magnr is None or jd is None:
                continue

            # Combine reference and difference fluxes to get total
            f_ref = 10 ** (-0.4 * magnr)
            f_diff = 10 ** (-0.4 * magpsf)
            sign = 1.0 if isdiffpos in ("t", "1", 1, True) else -1.0
            f_total = f_ref + sign * f_diff

            if f_total <= 0:
                continue

            mag_total = -2.5 * np.log10(f_total)

            # Propagate uncertainties
            # sigma_f_diff = 0.4 * ln(10) * f_diff * sigmapsf
            # sigma_f_ref  = 0.4 * ln(10) * f_ref  * sigmagnr
            sigma_f_diff = 0.4 * np.log(10) * f_diff * (sigmapsf or 0)
            sigma_f_ref = 0.4 * np.log(10) * f_ref * (sigmagnr or 0)
            sigma_f_total = np.sqrt(sigma_f_diff**2 + sigma_f_ref**2)
            mag_unc = 1.0857 * sigma_f_total / f_total

            jd_list.append(jd)
            mag_list.append(round(mag_total, 4))
            mag_unc_list.append(round(mag_unc, 4))
            filter_list.append(filt)
            objid_list.append(alert.get("objectId", ""))

        result = {
            "name": name,
            "ztf_id": ztf_id,
            "jd": jd_list,
            "mag": mag_list,
            "mag_unc": mag_unc_list,
            "filter": filter_list,
            "objectId": objid_list,
        }

        outpath = os.path.join(OUTPUT_DIR, f"{file_key}.json")
        with open(outpath, "w") as f:
            json.dump(result, f)
        print(f"Wrote {outpath} ({len(jd_list)} alerts)")


if __name__ == "__main__":
    main()
