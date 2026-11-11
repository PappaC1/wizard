import re
import pdfplumber
import pandas as pd
import numpy as np
import streamlit as st

st.set_page_config(page_title="SA Racing Wizard", page_icon="🧙‍♂️", layout="wide")

st.title("🧙‍♂️ South African Horseracing Prediction Engine")
st.caption("Upload any Race Coast / Computerform PDF to generate Value Picks, Dark Horses, and Exotic Bet Builders across the entire card.")


def parse_sa_pdf(uploaded_file) -> tuple[pd.DataFrame, str]:
    runners = []
    meeting_title = "South African Race Meeting"

    race_header_re = re.compile(r"RACE\s+(\d+)\s*-\s*(?:Abt/)?(\d+)m", re.IGNORECASE)
    runner_header_re = re.compile(
        r"^(?P<No>\d{1,2})\s+"
        r"(?P<Horse>[A-Z0-9\'\-\’]+(?:\s+[A-Z0-9\'\-\’]+)*?)\s+"
        r"(?P<Gear>[ASLF](?:\s+[BCPXHJKNZte])*)\s+"
        r"(?P<Draw>\d{1,2}|RESERVE\s*\d)\s+"
        r"(?P<Weight>\d{2}(?:\.\d)?)"
        r"(?:\s+\((?P<MR>\d+)\))?"
        r"(?:\s+\[(?P<LastMR>\d+)\])?$"
    )

    with pdfplumber.open(uploaded_file) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lines = [line.strip() for line in text.splitlines() if line.strip()]

            if page_idx == 1 and lines:
                meeting_title = lines

            page_race_match = None
            for line in lines[:6]:
                m = race_header_re.search(line)
                if m:
                    page_race_match = m
                    break
            if not page_race_match:
                continue

            current_race = int(page_race_match.group(1))
            race_distance = int(page_race_match.group(2))
            full_page_text = " ".join(lines)

            # 1. Extract Speed Ratings
            speed_map = {}
            speed_block = re.search(r"SPEED RATINGS:\s*(.*?)(?:BEST AVERAGE:|DAYS RESTED:)", full_page_text)
            if speed_block:
                for item in speed_block.group(1).split(";"):
                    sm = re.search(r"([A-Za-z\s\'\-\’]+?)\s+(-?\d+\.\d+)", item.strip())
                    if sm:
                        speed_map[sm.group(1).strip().upper()] = float(sm.group(2))

            # 2. Extract Days Rested
            rest_map = {}
            rest_block = re.search(r"DAYS RESTED:\s*(.*?)(?:\b1\s+[A-Z]{2,})", full_page_text)
            if rest_block:
                for item in rest_block.group(1).split(";"):
                    rm = re.search(r"([A-Za-z\s\'\-\’]+?)\s*\((\d+)\s*days\)", item.strip(), re.IGNORECASE)
                    if rm:
                        rest_map[rm.group(1).strip().upper()] = int(rm.group(2))

            # 3. Extract First-Time Blinkers / Tongue Tie Upgrades
            gear_upgrades = {}
            eq_block = re.search(r"Equipment Change:\s*(.*?)(?:SPEED RATINGS:)", full_page_text)
            if eq_block:
                eq_text = eq_block.group(1).upper()
                for part in eq_text.split(";"):
                    if "BL (" in part or "T/T ON" in part:
                        name_part = re.split(r"\bBL\b|\bT/T\b", part).strip()
                        if name_part:
                            gear_upgrades[name_part] = True

            # 4. Parse Individual Runners
            current_runner = None
            for line in lines:
                rm = runner_header_re.match(line)
                if rm:
                    if current_runner:
                        runners.append(current_runner)

                    horse_name = rm.group("Horse").strip().upper()
                    draw_raw = rm.group("Draw")
                    is_reserve = "RESERVE" in draw_raw.upper()
                    draw_num = int(draw_raw) if draw_raw.isdigit() else 99
                    mr_val = int(rm.group("MR")) if rm.group("MR") else 0
                    last_mr_val = int(rm.group("LastMR")) if rm.group("LastMR") else mr_val

                    current_runner = {
                        "Race": current_race,
                        "Dist": race_distance,
                        "No": int(rm.group("No")),
                        "Horse": horse_name,
                        "Reserve": is_reserve,
                        "Draw": draw_num,
                        "Wt": float(rm.group("Weight")),
                        "MR": mr_val,
                        "MR_Drop": max(0, last_mr_val - mr_val),
                        "Gear_Boost": 1.0 if horse_name in gear_upgrades else 0.0,
                        "Runs": 0,
                        "Wins": 0,
                        "Places": 0,
                        "Stakes": 0,
                        "Speed_Rating": speed_map.get(horse_name, np.nan),
                        "Days_Rested": rest_map.get(horse_name, 21),
                        "Trainer": "",
                        "Jockey": "",
                        "Comment": "",
                        "Last_Odds": 15.0,
                        "Finish_Positions": [],
                        "Lengths_Behind": [],
                        "Speed_MPS": []
                    }
                    continue

                if current_runner:
                    # Trainer & Jockey lines
                    if " by " in line and current_runner["Trainer"] == "":
                        parts = line.split()
                        if len(parts) >= 2:
                            current_runner["Trainer"] = " ".join(parts[-2:])

                    # Career Stats
                    stats_m = re.search(
                        r"Runs:\s*(\d+)\s+Wins:\s*(\d+)\s+Places:\s*(\d+)\s+Stakes Won:\s*R([\d,]+)",
                        line
                    )
                    if stats_m:
                        current_runner["Runs"] = int(stats_m.group(1))
                        current_runner["Wins"] = int(stats_m.group(2))
                        current_runner["Places"] = int(stats_m.group(3))
                        current_runner["Stakes"] = int(stats_m.group(4).replace(",", ""))
                        continue

                    # Comment line
                    if line.startswith("COMMENT:") or line.startswith("TRAINER COMMENT:"):
                        current_runner["Comment"] = line.split(":", 1).strip()
                        continue

                    # Past Run Line
                    run_m = re.match(
                        r"^[A-Z]\s+\d+\s+\d{2}\.\d{2}\.\d{2}\s+[A-Z]\s+\S+\s+(\d{3,4})\s+.*?\b(\d{1,2})\s+(\d+\.\d{2})\s+.*?\s+(\d{2,3}\.\d{2})\s+(\d+)/(\d+)",
                        line
                    )
                    if run_m:
                        dist_ran = int(run_m.group(1))
                        pos = int(run_m.group(2))
                        lengths = float(run_m.group(3))
                        time_sec = float(run_m.group(4))
                        num_odds = float(run_m.group(5))
                        den_odds = float(run_m.group(6))

                        current_runner["Finish_Positions"].append(pos)
                        current_runner["Lengths_Behind"].append(lengths)
                        if time_sec > 0:
                            current_runner["Speed_MPS"].append(dist_ran / time_sec)
                        if den_odds > 0:
                            current_runner["Last_Odds"] = round(num_odds / den_odds, 2)

            if current_runner:
                runners.append(current_runner)

    df = pd.DataFrame(runners)
    if df.empty:
        return df, meeting_title

    # Remove reserve runners from active scoring
    df = df[~df["Reserve"]].copy()

    # Feature Engineering
    df["Avg_MPS"] = df["Speed_MPS"].apply(lambda x: np.mean(x[-3:]) if x else np.nan)
    df["Avg_MPS"] = df["Avg_MPS"].fillna(df.groupby("Race")["Avg_MPS"].transform("mean")).fillna(16.0)

    df["Speed_Index"] = df["Speed_Rating"].fillna(
        df.groupby("Race")["Avg_MPS"].transform(lambda s: (s - s.mean()) / (s.std() + 1e-5))
    ).fillna(0.0)

    df["Avg_Lengths_Btn"] = df["Lengths_Behind"].apply(lambda x: np.mean(x[-2:]) if x else 6.0)
    df["Avg_Pos"] = df["Finish_Positions"].apply(lambda x: np.mean(x[-3:]) if x else 7.5)
    df["Earnings_Per_Run"] = np.where(df["Runs"] > 0, df["Stakes"] / df["Runs"], 0.0)
    df["Place_Strike"] = np.where(df["Runs"] > 0, (df["Wins"] * 2 + df["Places"]) / df["Runs"], 0.15)

    return df.drop(columns=["Finish_Positions", "Lengths_Behind", "Speed_MPS", "Reserve"]), meeting_title


def run_wizard_engine(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    scored = df.copy()

    def norm(s):
        if s.max() == s.min():
            return pd.Series(0.5, index=s.index)
        return (s - s.min()) / (s.max() - s.min())

    for race_id, grp in scored.groupby("Race"):
        idx = grp.index
        dist = grp["Dist"].iloc

        # 1. Weight-Adjusted Speed (Penalizes heavy weight over longer trips)
        wt_adj = (60.0 - grp["Wt"]) * (0.04 if dist >= 1400 else 0.025)
        speed_sc = norm(grp["Speed_Index"] + wt_adj)

        # 2. Class & Hidden MR Drop
        eff_mr = grp["MR"].replace(0, grp["MR"].median())
        class_sc = norm(eff_mr + (grp["MR_Drop"] * 1.5) + (grp["Earnings_Per_Run"] / 8000.0))

        # 3. Fitness / Recency Cycle (Sweet spot: 14 to 42 days)
        rest_penalty = np.where(grp["Days_Rested"] > 65, 0.25, 0.0)
        form_sc = norm((1.0 - norm(grp["Avg_Lengths_Btn"].clip(upper=12))) + grp["Place_Strike"] - rest_penalty)

        # 4. Tactical Draw (Stronger around turns >= 1400m)
        draw_weight = 1.0 if dist >= 1400 else 0.6
        draw_sc = (1.0 - norm(grp["Draw"].clip(upper=16))) * draw_weight + (0.5 * (1 - draw_weight))

        # 5. Gear / Equipment Upgrade
        gear_sc = grp["Gear_Boost"]

        # Raw Power Rating
        raw_power = (
            weights["speed"] * speed_sc +
            weights["class"] * class_sc +
            weights["form"] * form_sc +
            weights["draw"] * draw_sc +
            weights["gear"] * gear_sc
        )

        # Convert to Model Win Probability %
