"""
MANAGER Heuristic: Managerial Approach for Net-value Allocation, Grouped Eviction & Reallocation
"""
import pandas as pd
import datetime
import os
import time
import tkinter as tk
from tkinter import filedialog
import logging
import glob
import re

# Configuration

BATCH_PROCESSING_MODE = True
REST_INTERVAL_SECONDS = 1
DISABLE_PHASE_3 = False
DISABLE_PHASE2_REPLACEMENT = False

try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
except NameError:
    project_root = os.getcwd()

BASE_RESULTS_DIR = os.path.join(project_root, 'results')
HEURISTIC_RESULTS_DIR = os.path.join(BASE_RESULTS_DIR, 'MANAGER_heuristic')

HW = 65
HL = 60
BUFFER = 5
EPSILON_T = 0.1
EPSILON_P = 0.001
DEBUG_SHADOW = False

# Base Data Loading

def get_base_data(data_dir):
    base_data_path = os.path.dirname(data_dir)

    t1_path = os.path.join(data_dir, 'T1.csv')
    if not os.path.exists(t1_path):
        t1_path = os.path.join(base_data_path, 'T1.csv')
    try:
        model_df = pd.read_csv(t1_path)
        model_df = model_df.rename(columns={'m': 'M_ID'})
        model_data = model_df.set_index('M_ID').to_dict('index')
    except FileNotFoundError:
        return None, None

    t2_path = os.path.join(data_dir, 'T2.csv')
    if not os.path.exists(t2_path):
        t2_path = os.path.join(base_data_path, 'T2.csv')
    try:
        current_ac_df = pd.read_csv(t2_path)
        current_ac_df = current_ac_df.rename(columns={'c': 'id', 'Init_X': 'X_init', 'Init_Y': 'Y_init'})
        current_ac_df['ETA'] = 0.0
        if 'EP' in current_ac_df.columns:
            current_ac_df['P_Rej'] = current_ac_df['EP']
        current_ac_df['P_Arr'] = 0
        current_aircraft_data = current_ac_df.to_dict('records')
    except FileNotFoundError:
        return model_data, None

    for ac in current_aircraft_data:
        model_id = ac['M_ID']
        if model_id in model_data:
            ac['Width'] = model_data[model_id]['W']
            ac['Length'] = model_data[model_id]['L']
        else:
            ac['Width'] = 0
            ac['Length'] = 0

    return model_data, current_aircraft_data

def get_future_aircraft_data(t3_path, model_data, data_dir):
    if not t3_path:
        root = tk.Tk()
        root.withdraw()
        t3_path = filedialog.askopenfilename(
            title="Select the Future Aircraft CSV file (T3)",
            initialdir=data_dir,
            filetypes=[("CSV Files", "*.csv"), ("All files", "*.*")]
        )

    if not t3_path:
        return [], None

    try:
        future_ac_df = pd.read_csv(t3_path)
        future_ac_df = future_ac_df.rename(columns={'f': 'id'})
        future_aircraft_data = future_ac_df.to_dict('records')

        for ac in future_aircraft_data:
            model_id = ac['M_ID']
            if model_id in model_data:
                ac['Width'] = model_data[model_id]['W']
                ac['Length'] = model_data[model_id]['L']
            else:
                ac['Width'] = 0
                ac['Length'] = 0
        return future_aircraft_data, t3_path
    except Exception as e:
        return [], t3_path

# SHM Data Structures

class Aircraft:
    def __init__(self, data, is_current=False):
        self.id = data['id']
        self.M_ID = data.get('M_ID', 0)
        self.W = data.get('Width', 0)
        self.L = data.get('Length', 0)
        self.ETA = float(data.get('ETA', 0.0))
        self.ETD = float(data.get('ETD', 0.0))
        self.ServT = float(data.get('ServT', 0.0))
        self.EP = float(data.get('EP', data.get('P_Rej', 0.0)))
        self.P_Arr = float(data.get('P_Arr', 0.0))
        self.P_Dep = float(data.get('P_Dep', 0.0))
        self.is_current = is_current
        
        self.Accepted = 1 if is_current else 0
        self.X = float(data.get('X_init', 0.0)) if is_current else 0.0
        self.Y = float(data.get('Y_init', 0.0)) if is_current else 0.0
        self.Roll_In = 0.0 if is_current else 0.0
        self.Roll_Out = self.ServT if is_current else 0.0
        self.D_Arr = 0.0
        self.D_Dep = 0.0
        
        eff_w = self.W + BUFFER
        eff_l = self.L + BUFFER
        self.footprint = eff_w * eff_l
        self.NVS = self.EP / (self.footprint * self.ServT) if self.footprint * self.ServT > 0 else 0

    def copy(self):
        new_ac = Aircraft.__new__(Aircraft)
        new_ac.__dict__.update(self.__dict__)
        return new_ac

# SHM Core Functions

def same_x_lane(w, x, p):
    return (x < p.X + p.W + BUFFER - 1e-6) and (p.X < x + w + BUFFER - 1e-6)

def spatial_collision(w, l, x, y, p):
    is_x = (x < p.X + p.W + BUFFER - 1e-6) and (p.X < x + w + BUFFER - 1e-6)
    is_y = (y < p.Y + p.L + BUFFER - 1e-6) and (p.Y < y + l + BUFFER - 1e-6)
    return is_x and is_y

def time_windows_overlap(p, roll_in, roll_out):
    return (roll_in < p.Roll_Out - 1e-6) and (p.Roll_In < roll_out - 1e-6)

def corner_point_candidates(f, schedule):
    x_cands = {BUFFER, HW - BUFFER - f.W}
    y_cands = {BUFFER, HL - BUFFER - f.L}
    
    # Calculate the absolute maximum presence window for 'f'
    eco_arr_deadline = f.ETA + f.EP / f.P_Arr if f.P_Arr > 0 else float('inf')
    eco_dep_deadline = f.ETD + f.EP / f.P_Dep if f.P_Dep > 0 else float('inf')
    f_max_presence = max(eco_arr_deadline + f.ServT, eco_dep_deadline)
    
    for p in schedule:
        # Only generate points from planes that can physically coexist with 'f'
        if p.Roll_Out < f.ETA - 1e-6 or p.Roll_In > f_max_presence + 1e-6:
            continue
            
        x_cands.add(p.X + p.W + BUFFER)
        x_cands.add(p.X - f.W - BUFFER)
        y_cands.add(p.Y + p.L + BUFFER)
        y_cands.add(p.Y - f.L - BUFFER)
        
    valid_positions = []
    for x in x_cands:
        for y in y_cands:
            if BUFFER - 1e-6 <= x and x + f.W + BUFFER <= HW + 1e-6:
                if BUFFER - 1e-6 <= y and y + f.L + BUFFER <= HL + 1e-6:
                    valid_positions.append((round(x, 3), round(y, 3)))
    return sorted(list(set(valid_positions)), key=lambda p: (p[1], p[0]))

def generate_time_candidates(f, x, y, schedule):
    # Note: 'x' and 'y' are currently unused because we generate a superset of all 
    # possible blocker departure times across the entire hangar. They are kept in 
    # the signature for potential future position-dependent optimizations.
    raw_t_candidates = {f.ETA}
    
    for p in schedule:
        raw_t_candidates.add(p.Roll_Out + EPSILON_T)
            
    raw_t_candidates = {t for t in raw_t_candidates if t >= f.ETA - 1e-6}
    eco_deadline = f.ETA + f.EP / f.P_Arr if f.P_Arr > 0 else float('inf')
    raw_t_candidates = {t for t in raw_t_candidates if t <= eco_deadline + 1e-6}
    
    existing_events = set()
    for p in schedule:
        existing_events.add(p.Roll_In)
        existing_events.add(p.Roll_Out)
    sorted_events = sorted(list(existing_events))
    
    t_candidates = set()
    for t in raw_t_candidates:
        adjusted_t = t
        max_iterations = len(sorted_events) * 2 + 10
        iteration = 0
        limit_exceeded = False
        while True:
            iteration += 1
            if iteration > max_iterations:
                limit_exceeded = True
                break
            collision = False
            for e in sorted_events:
                if abs(adjusted_t - e) < EPSILON_T - 1e-6:
                    adjusted_t = e + EPSILON_T
                    collision = True
                    break
            if collision: continue
            
            roll_out = adjusted_t + f.ServT
            for e in sorted_events:
                if abs(roll_out - e) < EPSILON_T - 1e-6:
                    adjusted_t = max(adjusted_t, e + EPSILON_T - f.ServT)
                    collision = True
                    break
            if not collision: break
            
        if limit_exceeded:
            continue
            
        # After the loop, ensure adjusted_t hasn't gone below ETA
        if adjusted_t < f.ETA - 1e-6:
            continue  # skip this candidate entirely
            
        if adjusted_t >= f.ETA - 1e-6 and adjusted_t <= eco_deadline + 1e-6:
            t_candidates.add(round(adjusted_t, 3))
            
    return t_candidates

def passes_hard_constraints(f, x, y, roll_in, schedule):
    # Compute f's effective Roll_Out accounting for departure blocking ON f
    # (aircraft above f in the same lane where f arrived first)
    roll_out = roll_in + f.ServT
    max_iters = len(schedule)
    iters = 0
    changed = True
    while changed:
        iters += 1
        if iters > max_iters:
            break
        changed = False
        for p in schedule:
            if p.id == f.id:
                continue
            if same_x_lane(f.W, x, p):
                # p above f, f arrived first -> departure blocking on f
                p_above_f = (y + f.L + BUFFER <= p.Y + 1e-6)
                if p_above_f and roll_in <= p.Roll_In + 1e-6:
                    if roll_out > p.Roll_In + 1e-6:
                        req = p.Roll_Out + EPSILON_T
                        if roll_out < req - 1e-6:
                            roll_out = req
                            changed = True

    # Boundary check
    if not (x >= BUFFER - 1e-6 and y >= BUFFER - 1e-6
            and x + f.W + BUFFER <= HW + 1e-6
            and y + f.L + BUFFER <= HL + 1e-6):
        return False

    for p in schedule:
        if p.id == f.id:
            continue

        # ε_t separation for all event pairs
        if abs(roll_in - p.Roll_In) < EPSILON_T - 1e-6: return False
        if abs(roll_in - p.Roll_Out) < EPSILON_T - 1e-6: return False
        if abs(roll_out - p.Roll_In) < EPSILON_T - 1e-6: return False
        if abs(roll_out - p.Roll_Out) < EPSILON_T - 1e-6: return False

        # Spatial non-collision for temporally overlapping aircraft
        if time_windows_overlap(p, roll_in, roll_out):
            if spatial_collision(f.W, f.L, x, y, p):
                return False

        # Blocking constraints (only for same x-lane)
        if same_x_lane(f.W, x, p):
            # Check arrival pathway obstruction
            # f can't enter until p departs
            p_above_f = (y + f.L + BUFFER <= p.Y + 1e-6)
            if p_above_f and p.Roll_In <= roll_in + 1e-6:
                if roll_in < p.Roll_Out + EPSILON_T - 1e-6:
                    return False

            # Check arrival pathway obstruction
            # p can't enter until f departs - since p is already placed,
            # f must depart before p enters
            f_above_p = (p.Y + p.L + BUFFER <= y + 1e-6)
            if f_above_p and roll_in <= p.Roll_In + 1e-6:
                if roll_out > p.Roll_In - EPSILON_T + 1e-6:
                    return False

    return True

def update_schedule_roll_outs(schedule):
    for p in schedule:
        p.Roll_Out = p.Roll_In + p.ServT
        
    max_outer_iterations = len(schedule) ** 2 + 10
    iteration_count = 0
    changed = True
    while changed:
        iteration_count += 1
        if iteration_count > max_outer_iterations:
            return False
        changed = False
        for a in schedule:
            for b in schedule:
                if a.id == b.id: continue
                # Departure Blocking: Enforce FIFO exit constraints for aircraft in the same lane
                # then b is trapped behind a. So b MUST depart AFTER a departs.
                if same_x_lane(a.W, a.X, b) and a.Y >= b.Y + b.L + BUFFER - 1e-6:
                    # MILP: Only applies if b (deeper) arrived before a (shallower) OR both current
                    if b.Roll_In <= a.Roll_In + 1e-6:
                        # And they overlap in time
                        if a.Roll_In < b.Roll_Out - 1e-6:
                            if b.Roll_Out < a.Roll_Out + EPSILON_T - 1e-6:
                                b.Roll_Out = a.Roll_Out + EPSILON_T
                                changed = True

        if not changed:
            # Ensure ε_t separation between all Roll_Out events
            sorted_by_ro = sorted(schedule, key=lambda ac: (ac.Roll_Out, ac.id))
            for i in range(1, len(sorted_by_ro)):
                if sorted_by_ro[i].Roll_Out - sorted_by_ro[i-1].Roll_Out < EPSILON_T - 1e-9:
                    sorted_by_ro[i].Roll_Out = sorted_by_ro[i-1].Roll_Out + EPSILON_T
                    changed = True

            # Ensure ε_t separation between Roll_Out and Roll_In events
            for ac in schedule:
                for other in schedule:
                    if ac.id == other.id:
                        continue
                    if abs(ac.Roll_Out - other.Roll_In) < EPSILON_T - 1e-9:
                        ac.Roll_Out = other.Roll_In + EPSILON_T
                        changed = True
                            
    for p in schedule:
        p.D_Dep = max(0.0, p.Roll_Out - p.ETD)

    # GLOBAL FEASIBILITY CHECK: Catch cascading collisions, arrival blocking, and departure blocking
    for a in schedule:
        for b in schedule:
            if a.id == b.id:
                continue
            # Enforce spatial non-overlapping constraints
            if time_windows_overlap(a, b.Roll_In, b.Roll_Out):
                if spatial_collision(a.W, a.L, a.X, a.Y, b):
                    return False
                    
            # 2. Blocking Constraints
            if same_x_lane(a.W, a.X, b):
                # a is deeper, b is shallower
                b_above_a = (a.Y + a.L + BUFFER <= b.Y + 1e-6)
                if b_above_a:
                    # Arrival Blocking: if b (shallower) arrived before/same as a (deeper)
                    if b.Roll_In <= a.Roll_In + 1e-6:
                        if a.Roll_In < b.Roll_Out + EPSILON_T - 1e-6:
                            return False
                            
                    # Departure Blocking: if a (deeper) arrived before/same as b (shallower)
                    if a.Roll_In <= b.Roll_In + 1e-6:
                        # And they overlap in time
                        if b.Roll_In < a.Roll_Out - 1e-6:
                            if a.Roll_Out < b.Roll_Out + EPSILON_T - 1e-6:
                                return False

    return True

def calculate_shadow_area(x, y, w, schedule, roll_in, roll_out):
    floors = []
    floors.append((x, x + w, BUFFER))
    
    for p in schedule:
        if not time_windows_overlap(p, roll_in, roll_out):
            continue
        p_top = p.Y + p.L + BUFFER
        if p_top <= y + 1e-6:
            p_left = max(x, p.X)
            p_right = min(x + w, p.X + p.W)
            if p_left < p_right:
                floors.append((p_left, p_right, p_top))
                
    endpoints = set([x, x + w])
    for (left, right, h) in floors:
        endpoints.add(left)
        endpoints.add(right)
    endpoints = sorted(list(endpoints))
    
    shadow_area = 0.0
    for i in range(len(endpoints) - 1):
        e1 = endpoints[i]
        e2 = endpoints[i+1]
        width = e2 - e1
        if width <= 0: continue
        
        mid = (e1 + e2) / 2.0
        highest_h = BUFFER
        for (left, right, h) in floors:
            if left <= mid <= right:
                if h > highest_h:
                    highest_h = h
        
        height = y - highest_h
        if height > 0:
            shadow_area += width * height
            
    return shadow_area

def compute_net_placement_value(f, x, y, roll_in, schedule):
    # Early filter: if minimum own delay cost alone exceeds EP, this candidate is unprofitable
    arr_delay = max(0.0, roll_in - f.ETA)
    min_roll_out = roll_in + f.ServT
    dep_delay_min = max(0.0, min_roll_out - f.ETD)
    min_own_delay_cost = f.P_Arr * arr_delay + f.P_Dep * dep_delay_min
    if min_own_delay_cost >= f.EP - 1e-6:
        return float('-inf')

    saved_state = [(p.Roll_Out, p.D_Dep) for p in schedule]
    
    f_temp = f.copy()
    f_temp.X, f_temp.Y, f_temp.Roll_In = x, y, roll_in
    f_temp.Roll_Out = roll_in + f.ServT
    
    schedule.append(f_temp)
    try:
        is_feasible = update_schedule_roll_outs(schedule)
        
        if not is_feasible:
            return float('-inf')
        
        arr_delay = max(0.0, f_temp.Roll_In - f.ETA)
        dep_delay = max(0.0, f_temp.Roll_Out - f.ETD)
        own_delay_cost = f.P_Arr * arr_delay + f.P_Dep * dep_delay
        
        imposed_cost = 0.0
        for i, (ro, dd) in enumerate(saved_state):
            added = schedule[i].Roll_Out - ro
            if added > 1e-6:
                imposed_cost += schedule[i].P_Dep * added
        
        net_value = f.EP - own_delay_cost - imposed_cost
        shadow_area = calculate_shadow_area(x, y, f.W, schedule[:-1], roll_in, roll_in + f.ServT)
        pos_penalty = EPSILON_P * y + EPSILON_P * shadow_area
        
        if DEBUG_SHADOW:
            print(f"    [Shadow Debug] Trying ({x:5.1f}, {y:5.1f}) -> shadow_area={shadow_area:6.1f}, penalty={pos_penalty:6.4f}")
            
        return net_value - pos_penalty
    finally:
        schedule.pop()
        for i, (ro, dd) in enumerate(saved_state):
            schedule[i].Roll_Out = ro
            schedule[i].D_Dep = dd

def find_best_candidate(f, schedule):
    positions = corner_point_candidates(f, schedule)
    times = generate_time_candidates(f, 0, 0, schedule)
    best_cand = None
    best_nv = float('-inf')
    
    for (x, y) in positions:
        for roll_in in times:
            if not passes_hard_constraints(f, x, y, roll_in, schedule):
                continue
            
            nv = compute_net_placement_value(f, x, y, roll_in, schedule)
            if nv > best_nv:
                best_nv = nv
                best_cand = {'x': x, 'y': y, 'roll_in': roll_in, 'net_value': nv}
                
    return best_cand

def place_aircraft(f, best, schedule):
    f.Accepted = 1
    f.X = best['x']
    f.Y = best['y']
    f.Roll_In = best['roll_in']
    f.Roll_Out = f.Roll_In + f.ServT
    f.D_Arr = max(0.0, f.Roll_In - f.ETA)
    schedule.append(f)
    update_schedule_roll_outs(schedule)

def find_eviction_interfering_groups(f, schedule):
    interfering_groups = []
    positions = corner_point_candidates(f, schedule)
    
    for (x, y) in positions:
        times = generate_time_candidates(f, x, y, schedule)
        for roll_in in times:
            roll_out = roll_in + f.ServT
            interfering_group = []
            possible = True
            
            for p in schedule:
                # 1. Spatial collision (requires time overlap)
                if time_windows_overlap(p, roll_in, roll_out):
                    if spatial_collision(f.W, f.L, x, y, p):
                        if p.is_current:
                            possible = False
                            break
                        interfering_group.append(p)
                        continue
                
                # 2. Arrival blocking constraints (only for same x-lane)
                if same_x_lane(f.W, x, p):
                    # Check arrival pathway obstruction
                    p_above_f = (y + f.L + BUFFER <= p.Y + 1e-6)
                    if p_above_f and p.Roll_In <= roll_in + 1e-6:
                        if roll_in < p.Roll_Out + EPSILON_T - 1e-6:
                            if p.is_current:
                                possible = False
                                break
                            if p not in interfering_group:
                                interfering_group.append(p)
                            continue
                    
                    # Check arrival pathway obstruction
                    f_above_p = (p.Y + p.L + BUFFER <= y + 1e-6)
                    if f_above_p and roll_in <= p.Roll_In + 1e-6:
                        if roll_out > p.Roll_In - EPSILON_T + 1e-6:
                            if p.is_current:
                                possible = False
                                break
                            if p not in interfering_group:
                                interfering_group.append(p)
                            continue
                        
            if possible and len(interfering_group) > 0:
                interfering_group_ids = tuple(sorted(p.id for p in interfering_group))
                interfering_groups.append({
                    'position': (x, y),
                    'aircraft_to_evict': interfering_group,
                    'interfering_group_ids': interfering_group_ids
                })
            
    unique_interfering_groups = []
    seen = set()
    for c in interfering_groups:
        if c['interfering_group_ids'] not in seen:
            seen.add(c['interfering_group_ids'])
            unique_interfering_groups.append(c)
            
    return unique_interfering_groups

def evaluate_interfering_group_eviction(f, interfering_group, schedule):
    evict_set_ids = set(e.id for e in interfering_group['aircraft_to_evict'])
    temp_schedule = [p.copy() for p in schedule if p.id not in evict_set_ids]
    
    is_feasible = update_schedule_roll_outs(temp_schedule)
    if not is_feasible:
        return float('-inf')
    
    saved_blocking_costs = 0.0
    for temp_p in temp_schedule:
        orig_p = next(p for p in schedule if p.id == temp_p.id)
        if temp_p.D_Dep < orig_p.D_Dep - 1e-6:
            saved_blocking_costs += orig_p.P_Dep * (orig_p.D_Dep - temp_p.D_Dep)
            
    best_f = find_best_candidate(f, temp_schedule)
    if best_f is None:
        return float('-inf')
        
    value_gained = best_f['net_value']
    value_lost = sum(e.EP for e in interfering_group['aircraft_to_evict'])
    delays_recovered = sum(e.P_Arr * e.D_Arr + e.P_Dep * e.D_Dep for e in interfering_group['aircraft_to_evict'])
    
    return value_gained - value_lost + saved_blocking_costs + delays_recovered

# Main Execution

def run_heuristic_instance(current_aircraft_data, future_aircraft_data, t3_file_path, output_dir_path):
    start_time = time.time()

    if not future_aircraft_data:
        print("No future aircraft data provided. Aborting instance run.")
        return None

    current_aircraft = [Aircraft(ac, is_current=True) for ac in current_aircraft_data] if current_aircraft_data else []
    future_aircraft = [Aircraft(ac, is_current=False) for ac in future_aircraft_data]

    future_aircraft.sort(key=lambda ac: (-ac.NVS, -ac.P_Arr, ac.ETA))

    schedule = current_aircraft.copy()
    # Initialize baseline delays for current aircraft
    update_schedule_roll_outs(schedule)
    rejected_list = []

    log_func = logging.info if BATCH_PROCESSING_MODE else print

    log_func("\nPhase 1: Net-value Allocation")
    for i, f in enumerate(future_aircraft):
        log_func(f"  ({i+1}/{len(future_aircraft)}) Trying to place Aircraft {f.id} (NVS: {f.NVS:.4f})...")

        best = find_best_candidate(f, schedule)

        if best and best['net_value'] > 0:
            place_aircraft(f, best, schedule)
            log_func(f"    -> Placed at (X={f.X:.2f}, Y={f.Y:.2f}) | Roll-In: {f.Roll_In:.2f}")
        else:
            # Phase 2: Grouped Eviction
            interfering_groups = find_eviction_interfering_groups(f, schedule)
            best_interfering_group = None
            best_gain = 0.0

            for interfering_group in interfering_groups:
                gain = evaluate_interfering_group_eviction(f, interfering_group, schedule)
                if gain > best_gain:
                    best_gain = gain
                    best_interfering_group = interfering_group

            if best_interfering_group and best_gain > 0:
                evicted = best_interfering_group['aircraft_to_evict']
                log_func(f"    -> Evicting {len(evicted)} aircraft to make room for {f.id} (Gain: {best_gain:.2f})")
                
                evict_ids = set(e.id for e in evicted)
                schedule = [p for p in schedule if p.id not in evict_ids]
                update_schedule_roll_outs(schedule)

                best_f = find_best_candidate(f, schedule)
                if best_f is None or best_f['net_value'] <= 0:
                    # Eviction didn't actually help — can't place f
                    f.Accepted = 0
                    f.X, f.Y, f.Roll_In, f.Roll_Out, f.D_Arr, f.D_Dep = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
                    rejected_list.append(f)
                    log_func(f"    -> Eviction failed for {f.id}, re-placing evicted aircraft.")
                    # Try to re-place the evicted aircraft since we're not using the spot
                    evicted_sorted = sorted(evicted, key=lambda e: e.NVS, reverse=True)
                    for e in evicted_sorted:
                        re_best = find_best_candidate(e, schedule)
                        if re_best and re_best['net_value'] > 0:
                            place_aircraft(e, re_best, schedule)
                            log_func(f"      -> Re-placed evicted aircraft {e.id}")
                        else:
                            e.Accepted = 0
                            e.X, e.Y, e.Roll_In, e.Roll_Out, e.D_Arr, e.D_Dep = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
                            rejected_list.append(e)
                            log_func(f"      -> Rejected evicted aircraft {e.id}")
                    continue
                place_aircraft(f, best_f, schedule)

                # Phase 2: Immediate Re-placement (Reallocation)
                if not DISABLE_PHASE2_REPLACEMENT:
                    evicted_sorted = sorted(evicted, key=lambda e: e.NVS, reverse=True)
                    for e in evicted_sorted:
                        re_best = find_best_candidate(e, schedule)
                        if re_best and re_best['net_value'] > 0:
                            place_aircraft(e, re_best, schedule)
                            log_func(f"      -> Re-placed evicted aircraft {e.id}")
                        else:
                            e.Accepted = 0
                            e.X, e.Y, e.Roll_In, e.Roll_Out, e.D_Arr, e.D_Dep = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
                            rejected_list.append(e)
                            log_func(f"      -> Rejected evicted aircraft {e.id}")
                else:
                    for e in evicted:
                        e.Accepted = 0
                        e.X, e.Y, e.Roll_In, e.Roll_Out, e.D_Arr, e.D_Dep = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
                        rejected_list.append(e)
                        log_func(f"      -> Phase 2 Replacement Disabled. Rejected evicted aircraft {e.id}")
                continue
            
            f.Accepted = 0
            f.X, f.Y, f.Roll_In, f.Roll_Out, f.D_Arr, f.D_Dep = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
            rejected_list.append(f)
            log_func(f"    -> Could not be placed or profitably evict. Rejected.")

    log_func("\nPhase 3: Freed-slot Recovery (Final sweep for rejected aircraft)")
    if not DISABLE_PHASE_3:
        rejected_by_nvs = sorted(rejected_list, key=lambda x: x.NVS, reverse=True)
        still_rejected = []
        for f in rejected_by_nvs:
            best = find_best_candidate(f, schedule)
            if best and best['net_value'] > 0:
                place_aircraft(f, best, schedule)
                log_func(f"  -> Recovered rejected aircraft {f.id} at (X={f.X:.2f}, Y={f.Y:.2f})")
            else:
                still_rejected.append(f)
    else:
        still_rejected = rejected_list
        log_func("  -> Phase 3 Disabled.")

    all_aircraft = schedule + still_rejected

    if not all_aircraft:
        log_func("\nNo aircraft were processed. No output file generated.")
        return None

    results = []
    for ac in all_aircraft:
        results.append({
            'Aircraft_ID': ac.id,
            'Accepted': ac.Accepted,
            'Width': ac.W,
            'Length': ac.L,
            'ETA': ac.ETA,
            'Roll_In': ac.Roll_In,
            'X': ac.X,
            'Y': ac.Y,
            'ServT': ac.ServT,
            'ETD': ac.ETD,
            'Roll_Out': ac.Roll_Out,
            'D_Arr': ac.D_Arr,
            'D_Dep': ac.D_Dep,
            'EP': ac.EP,
            'P_Arr': ac.P_Arr,
            'P_Dep': ac.P_Dep,
            'Hangar_Width': HW,
            'Hangar_Length': HL,
            'StartDate': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        })

    df = pd.DataFrame(results)
    
    all_original_ids = ([ac['id'] for ac in current_aircraft_data] if current_aircraft_data else []) + [ac['id'] for ac in future_aircraft_data]
    df = df.set_index('Aircraft_ID').reindex(all_original_ids).reset_index()

    total_cost_reject = df[df['Accepted'] == 0]['EP'].sum()
    total_cost_d_arr = (df['D_Arr'] * df['P_Arr']).sum()
    total_cost_d_dep = (df['D_Dep'] * df['P_Dep']).sum()
    future_ids = [ac['id'] for ac in future_aircraft_data]
    future_accepted_mask = (df['Accepted']==1) & (df['Aircraft_ID'].isin(future_ids))
    total_positioning_penalty = (df.loc[future_accepted_mask, 'X'].sum() + df.loc[future_accepted_mask, 'Y'].sum()) * EPSILON_P

    total_cost = total_cost_reject + total_cost_d_arr + total_cost_d_dep
    total_z = total_cost + total_positioning_penalty
    
    total_EP_accepted = df[df['Accepted'] == 1]['EP'].sum()
    new_objective_max = total_EP_accepted - total_cost_d_arr - total_cost_d_dep - total_positioning_penalty
    
    processing_time = time.time() - start_time

    static_data_map = {ac['id']: ac for ac in ((current_aircraft_data if current_aircraft_data else []) + future_aircraft_data)}
    for i, row in df.iterrows():
        if pd.isna(row['Accepted']) or row['Accepted'] == 0:
            original_ac = static_data_map[row['Aircraft_ID']]
            df.loc[i, 'Accepted'] = 0
            df.loc[i, 'X'] = 0.0
            df.loc[i, 'Y'] = 0.0
            df.loc[i, 'Roll_In'] = 0.0
            df.loc[i, 'Roll_Out'] = 0.0
            df.loc[i, 'D_Arr'] = 0.0
            df.loc[i, 'D_Dep'] = 0.0
            for col in ['Width', 'Length', 'ETA', 'ServT', 'ETD', 'EP', 'P_Arr', 'P_Dep']:
                df_col = col
                if col == 'EP': df_col = 'EP'
                elif col == 'P_Arr': df_col = 'P_Arr'
                elif col == 'P_Dep': df_col = 'P_Dep'
                
                df.loc[i, df_col] = original_ac.get(col, 0)
                
            df.loc[i, 'Hangar_Width'] = HW
            df.loc[i, 'Hangar_Length'] = HL
            df.loc[i, 'StartDate'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    final_columns = [
        'Aircraft_ID', 'Accepted', 'Width', 'Length', 'ETA', 'Roll_In', 'X', 'Y',
        'ServT', 'ETD', 'Roll_Out', 'D_Arr', 'D_Dep', 'EP',
        'P_Arr', 'P_Dep', 'Hangar_Width',
        'Hangar_Length', 'StartDate'
    ]
    output_df = df[final_columns].fillna(0)

    t3_basename = os.path.splitext(os.path.basename(t3_file_path))[0]
    instance_name = t3_basename.replace('T3-', '')
    output_filename = f'Heuristic_Solution_{instance_name}.csv'
    full_path = os.path.join(output_dir_path, output_filename)

    os.makedirs(output_dir_path, exist_ok=True)
    output_df.to_csv(full_path, index=False, float_format='%.2f')

    relative_solution_path = os.path.relpath(full_path, project_root)
    log_func(f"\nFinal solution for {t3_basename} saved to '{relative_solution_path}'")

    num_accepted_total = int(output_df['Accepted'].sum())
    num_total_aircraft = len(all_original_ids)

    return {
        "Instance_Name": instance_name,
        "New_Objective_Max": new_objective_max,
        "Total_EP_Accepted": total_EP_accepted,
        "Objective_Value_Z": total_z,
        "Total_Cost": total_cost,
        "Cost_Rejection": total_cost_reject,
        "Cost_Arrival_Delay": total_cost_d_arr,
        "Cost_Departure_Delay": total_cost_d_dep,
        "Cost_Positioning": total_positioning_penalty,
        "Processing_Time_Sec": processing_time,
        "Accepted_Aircraft": num_accepted_total,
        "Total_Aircraft": num_total_aircraft,
    }

def extract_number_from_filename(filepath):
    basename = os.path.basename(filepath)
    matches = re.findall(r'\d+', basename)
    if matches:
        return tuple(int(m) for m in matches)
    return (0,)

def run_for_mode(data_folder_name):
    DATA_DIR = os.path.join(project_root, 'data', data_folder_name)
    OUTPUT_DIR_PATH = os.path.join(HEURISTIC_RESULTS_DIR, data_folder_name)
    LOG_FILE_PATH = os.path.join(HEURISTIC_RESULTS_DIR, f'log_{data_folder_name}.txt')
    SUMMARY_EXCEL_PATH = os.path.join(HEURISTIC_RESULTS_DIR, f'Heuristic_Summary_Report_{data_folder_name}.xlsx')
    
    t3_file_paths = glob.glob(os.path.join(DATA_DIR, 'T3-*.csv'))
    T3_FILE_LIST = sorted(t3_file_paths, key=extract_number_from_filename)
    
    # Skip old out-of-date congested instances inside the random dataset
    if data_folder_name == 'random':
        T3_FILE_LIST = [f for f in T3_FILE_LIST if '_congested_' not in os.path.basename(f)]

    os.makedirs(OUTPUT_DIR_PATH, exist_ok=True)
    os.makedirs(HEURISTIC_RESULTS_DIR, exist_ok=True)

    all_run_summaries = []

    if not BATCH_PROCESSING_MODE:
        model_data, current_aircraft_base = get_base_data(DATA_DIR)
        if model_data is None: return

        future_aircraft, t3_path = get_future_aircraft_data(None, model_data, DATA_DIR)
        if not t3_path: return

        results = run_heuristic_instance(current_aircraft_base, future_aircraft, t3_path, OUTPUT_DIR_PATH)

        if results:
            all_run_summaries.append(results)
            print("\n" + "="*50)
            print("Final Heuristic Solution Summary:")
            print(f"Total Objective Value (Z MAX): {results['New_Objective_Max']:,.2f}")
            print(f"Total Expected Profit (EP) of Accepted: {results['Total_EP_Accepted']:,.2f}")
            label_width = 30
            print(f"  - {'Total Arrival Delay Penalty:'.ljust(label_width)} {results['Cost_Arrival_Delay']:,.2f}")
            print(f"  - {'Total Departure Delay Penalty:'.ljust(label_width)} {results['Cost_Departure_Delay']:,.2f}")
            print(f"  - {'Total Positioning Penalty:'.ljust(label_width)} {results['Cost_Positioning']:,.2f}")
            print("-" * 50)
            print(f"  - {'Algorithm Processing Time:'.ljust(label_width)} {results['Processing_Time_Sec']:.4f} seconds")
            print("="*50 + "\n")
    else:
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
            
        logging.basicConfig(
            level=logging.INFO, format='%(message)s',
            handlers=[
                logging.FileHandler(LOG_FILE_PATH, mode='w'),
                logging.StreamHandler()
            ]
        )

        relative_log_path = os.path.relpath(LOG_FILE_PATH, project_root)

        logging.info("="*80)
        logging.info(f"BATCH PROCESSING MODE ACTIVATED")
        logging.info(f"Dataset selected: {data_folder_name.upper()}")
        logging.info(f"Start Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logging.info(f"Log file will be saved to: {relative_log_path}")
        logging.info("="*80 + "\n")

        model_data, current_aircraft_base = get_base_data(DATA_DIR)
        if model_data is None:
            logging.error("Could not load base T1/T2 data. Aborting batch process.")
            return

        for i, t3_file in enumerate(T3_FILE_LIST):
            logging.info(f"--- RUN {i+1}/{len(T3_FILE_LIST)}: PROCESSING FILE: {os.path.basename(t3_file)} ---")

            future_aircraft, t3_path = get_future_aircraft_data(t3_file, model_data, DATA_DIR)

            if not future_aircraft:
                logging.error(f"Could not load or process future aircraft from {t3_file}. Skipping.")
                logging.info("\n" + "="*80 + "\n")
                continue

            results = run_heuristic_instance(current_aircraft_base, future_aircraft, t3_path, OUTPUT_DIR_PATH)

            if results:
                all_run_summaries.append(results)
                logging.info("\n" + "-"*50)
                logging.info("Heuristic Solution Summary:")
                logging.info(f"Total Objective Value (Z MAX): {results['New_Objective_Max']:,.2f}")
                logging.info(f"Total Expected Profit (EP) of Accepted: {results['Total_EP_Accepted']:,.2f}")
                label_width = 30
                logging.info(f"  - {'Total Arrival Delay Penalty:'.ljust(label_width)} {results['Cost_Arrival_Delay']:,.2f}")
                logging.info(f"  - {'Total Departure Delay Penalty:'.ljust(label_width)} {results['Cost_Departure_Delay']:,.2f}")
                logging.info(f"  - {'Total Positioning Penalty:'.ljust(label_width)} {results['Cost_Positioning']:,.2f}")
                logging.info("-" * 50)
                logging.info(f"  - {'Algorithm Processing Time:'.ljust(label_width)} {results['Processing_Time_Sec']:.4f} seconds")
                logging.info("-" * 50)

            logging.info(f"--- END OF RUN {i+1}/{len(T3_FILE_LIST)} ---")

            if i < len(T3_FILE_LIST) - 1:
                logging.info(f"\nPausing for {REST_INTERVAL_SECONDS} seconds...")
                time.sleep(REST_INTERVAL_SECONDS)

            logging.info("\n" + "="*80 + "\n")

        logging.info("Batch processing finished.")

    if all_run_summaries:
        log_func = logging.info if BATCH_PROCESSING_MODE else print
        try:
            new_summary_df = pd.DataFrame(all_run_summaries)
            relative_summary_path = os.path.relpath(SUMMARY_EXCEL_PATH, project_root)

            log_func(f"\nCreating/Overwriting summary report: '{relative_summary_path}'")
            
            with pd.ExcelWriter(SUMMARY_EXCEL_PATH, engine='openpyxl') as writer:
                new_summary_df.to_excel(writer, index=False, sheet_name='Summary')
                worksheet = writer.sheets['Summary']
                for col in worksheet.columns:
                    max_length = 0
                    column = col[0].column_letter
                    for cell in col:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = (max_length + 2)
                    worksheet.column_dimensions[column].width = adjusted_width

            log_func("\n" + "="*80)
            log_func(f"SUCCESS: Summary report has been saved/updated in:")
            log_func(f"'{relative_summary_path}'")
            log_func("="*80)
        except Exception as e:
            log_func(f"\nERROR: Could not save the summary Excel report. Reason: {e}")
            log_func("Please ensure you have 'openpyxl' installed (`pip install openpyxl`).")

def main():
    choice = ''
    while choice not in ['1', '2', '3']:
        choice = input("Please select the dataset to run:\n1: incremental\n2: random\n3: Both (run 1, then 2)\nEnter choice (1, 2, or 3): ")

    modes_to_run = []
    if choice == '1':
        modes_to_run.append('incremental')
    elif choice == '2':
        modes_to_run.append('random')
    elif choice == '3':
        modes_to_run.append('incremental')
        modes_to_run.append('random')

    for i, mode in enumerate(modes_to_run):
        run_for_mode(mode)
        if len(modes_to_run) > 1 and i < len(modes_to_run) - 1:
            print(f"\n{'='*80}\nMODE '{mode.upper()}' COMPLETE. Pausing for 10 seconds before starting the next mode...\n{'='*80}\n")
            time.sleep(10)

    print(f"\n{'='*80}\nALL REQUESTED TASKS ARE COMPLETE.\n{'='*80}")

if __name__ == '__main__':
    main()
