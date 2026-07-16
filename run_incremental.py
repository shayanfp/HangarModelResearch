import os
import subprocess
import shutil
import glob

RESULTS_DIR = "results/incremental"
GAMS_MODEL_PATH = "src/gams_model.gms"
PROCESSES_TO_KILL = ["cplex.exe", "gdxxrw.exe"]

GAMS_EXE = "gams"

SCENARIOS_FULL_OPTIMALITY = list(range(6, 41, 2))
SCENARIOS_TIME_LIMITED = list(range(60, 161, 20))

def kill_lingering_processes(process_names):
    print("Terminating lingering solver and data processes...")
    for process in process_names:
        subprocess.run(
            ["taskkill", "/f", "/im", process],
            capture_output=True,
            check=False
        )

def run_gams_scenario(n_val, total_n, sample_id, reslim, optcr, file_path, file_name, f_val=3):
    n_str = f"{n_val:02d}"
    total_n_str = f"{total_n:02d}"
    f_val_str = f"{f_val:02d}"
    sample_id_str = f"{sample_id:02d}"

    print(f"\n==================================================")
    print(f"Running scenario: N={n_val}, Sample={sample_id} (Limit: {reslim}s, Gap: {optcr})")
    print(f"==================================================")
    
    list_file_path = os.path.join(RESULTS_DIR, f"run_N{n_str}_S{sample_id_str}.lst")
    log_file_path = os.path.join(RESULTS_DIR, f"run_N{n_str}_S{sample_id_str}.log")

    # Set dynamic MIP interval
    mip_interval = 1 if n_val <= 40 else 100
    with open("cplex.opt", "w") as optf:
        optf.write(f"mipinterval {mip_interval}\n")

    command = [
        GAMS_EXE, GAMS_MODEL_PATH,
        f"--NVAL={n_str}",
        f"--TOTAL_N={total_n_str}",
        f"--FVAL={f_val_str}",
        f"--SAMPLE_ID={sample_id_str}",
        f"--FILEPATH={file_path}",
        f"--FILENAME={file_name}",
        f"o={list_file_path}",
        f"lf={log_file_path}",
        "lo=2",
        f"reslim={reslim}",
        f"optcr={optcr}",
        "optfile=1"
    ]

    try:
        print("\n--- Executing GAMS optimization solver ---")
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        # CPLEX exiting on time limit exits with non-zero, which is expected.
        pass
    except FileNotFoundError:
        print("Error: GAMS executable not found. Ensure it is in PATH.")
        exit()
    except Exception as e:
        print(f"Error executing GAMS: {e}")
    finally:
        kill_lingering_processes(PROCESSES_TO_KILL)

    # Check if the report was generated to determine success
    report_pattern = f"SolutionReport_N{n_str}_S{sample_id_str}*.csv"
    report_files = glob.glob(report_pattern)
    
    if report_files:
        try:
            for report_file in report_files:
                # Determine final destination path (use results_dir if it exists, otherwise RESULTS_DIR)
                target_dir = results_dir if 'results_dir' in locals() else RESULTS_DIR
                destination_path = os.path.join(target_dir, os.path.basename(report_file))
                shutil.move(report_file, destination_path)
                print(f"--> Success! Solution report saved to: {destination_path}")
                print("--------------------------------------------------")
        except Exception as e:
            print(f"Error moving report file: {e}")
            print("--------------------------------------------------")
    else:
        print(f"--> Failure: No solution report found matching '{report_pattern}'. GAMS may have crashed.")
        print("--------------------------------------------------")

def final_cleanup():
    print("\nCleaning up temporary GDX files...")
    temp_files = glob.glob("TEMP_T*.gdx")
    temp_dirs = glob.glob("225*")
    for item in temp_files:
        try: os.remove(item)
        except OSError: pass
    for item in temp_dirs:
        if os.path.isdir(item):
            try: shutil.rmtree(item)
            except OSError: pass

def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    kill_lingering_processes(PROCESSES_TO_KILL)

    file_path_segment = "/incremental"

    # Group 1: Full Optimality
    for n in SCENARIOS_FULL_OPTIMALITY:
        total_n_value = n + 2
        file_name_segment = f"INC-{n:02d}"
        run_gams_scenario(n, total_n_value, 1, reslim=86400, optcr=0.0, file_path=file_path_segment, file_name=file_name_segment)

    # Group 2: Time Limited
    for n in SCENARIOS_TIME_LIMITED:
        total_n_value = n + 2
        file_name_segment = f"INC-{n:02d}"
        run_gams_scenario(n, total_n_value, 1, reslim=3600, optcr=0.0, file_path=file_path_segment, file_name=file_name_segment)

    final_cleanup()

if __name__ == "__main__":
    main()
