import pandas as pd

FEATURE_COLUMNS = ["Age", "Parch", "SibSp", "Embarked_S", "Sex_male", "Pclass", "Fare", "Embarked_Q"]


def preprocess(payload: dict) -> pd.DataFrame:
    df = pd.DataFrame([{
        "Age": payload.get("Age"),
        "Parch": payload.get("Parch"),
        "SibSp": payload.get("SibSp"),
        "Fare": payload.get("Fare"),
        "Pclass": payload.get("Pclass"),
        "Sex": payload.get("Sex"),
        "Embarked": payload.get("Embarked"),
    }])

    df = df.fillna(0)

    sex_dummies = pd.get_dummies(df["Sex"], prefix="Sex")
    if "Sex_male" not in sex_dummies.columns:
        sex_dummies["Sex_male"] = 0
    df["Sex_male"] = sex_dummies["Sex_male"].astype(int)

    embarked_dummies = pd.get_dummies(df["Embarked"], prefix="Embarked")
    for col in ["Embarked_Q", "Embarked_S"]:
        df[col] = embarked_dummies[col].astype(int) if col in embarked_dummies.columns else 0

    df = df[FEATURE_COLUMNS]
    return df
