import os
import subprocess
import shutil
import glob

GAMS_MODEL_PATH = "src/gams_model.gms"
PROCESSES_TO_KILL = ["cplex.exe", "gdxxrw.exe"]

GAMS_EXE = "gams"
SAMPLES = [1, 2, 3]

def kill_lingering_processes(process_names):
    print("Terminating lingering solver and data processes...")
    for process in process_names:
        subprocess.run(
            ["taskkill", "/f", "/im", process],
            capture_output=True,
            check=False
        )

def run_gams_scenario(n_val, total_n, sample_id, reslim, optcr, file_path, file_name, results_dir, f_val=3):
    n_str = f"{n_val:02d}"
    total_n_str = f"{total_n:02d}"
    f_val_str = f"{f_val:02d}"
    sample_id_str = f"{sample_id:02d}"

    print(f"\n==================================================")
    print(f"Running scenario: N={n_val}, Sample={sample_id} (Limit: {reslim}s, Gap: {optcr})")
    print(f"==================================================")
    
    list_file_path = os.path.join(results_dir, f"run_N{n_str}_S{sample_id_str}.lst")
    log_file_path = os.path.join(results_dir, f"run_N{n_str}_S{sample_id_str}.log")

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
    kill_lingering_processes(PROCESSES_TO_KILL)

    # Congestion levels now match filenames and folder paths directly
    scenarios_to_run = [
        ("1.0x", "results/congestion/run_1.0x"),
        ("1.4x", "results/congestion/run_1.4x"),
        ("2.0x", "results/congestion/run_2.0x"),
        ("2.5x", "results/congestion/run_2.5x"),
        ("3.3x", "results/congestion/run_3.3x")
    ]
    
    file_path_segment = "/congestion"
    n_value = 20
    total_n_value = n_value + 2

    for level, results_dir in scenarios_to_run:
        os.makedirs(results_dir, exist_ok=True)
        print(f"\nProcessing congestion level: {level} -> Output folder: {results_dir}")
        for s in SAMPLES:
            file_name_segment = f"{total_n_value}-{s:02d}_congested_{level}"
            run_gams_scenario(
                n_val=n_value, 
                total_n=total_n_value, 
                sample_id=s, 
                reslim=7200, 
                optcr=0.0, 
                file_path=file_path_segment, 
                file_name=file_name_segment,
                results_dir=results_dir
            )
            print("-" * 50)

    final_cleanup()

if __name__ == "__main__":
    main()
