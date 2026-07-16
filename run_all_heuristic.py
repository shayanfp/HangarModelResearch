import sys
from src.MANAGER_heuristic import run_for_mode

def main():
    datasets = ['congestion', 'incremental', 'random']
    for ds in datasets:
        print(f"\n--- Running Heuristic for Dataset: {ds} ---")
        run_for_mode(ds)

if __name__ == '__main__':
    main()
