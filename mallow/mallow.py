from state import predictor
from state import paths

if __name__ == "__main__":
    state_csv, prediction_txt, model_path = paths.STATE_CSV, paths.PREDICTION_TXT, paths.MODEL
    interval = predictor.UPDATE_SEC
    predictor.Sidecar(predictor.load_model(model_path), state_csv,
                      prediction_txt, interval, predictor.STALE_SEC).run()
