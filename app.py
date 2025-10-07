import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.datasets import load_iris

st.set_page_config(page_title="Explainable AI Demo", layout="wide")

st.title("🌸 Explainable AI Demo with SHAP")
st.write("This app explains a Random Forest model trained on the Iris dataset.")

@st.cache_data
def load_and_train():
    iris = load_iris()
    X = pd.DataFrame(iris.data, columns=iris.feature_names)
    y = iris.target
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)
    
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    
    return X, X_train, X_test, y_train, y_test, iris.target_names, model

X, X_train, X_test, y_train, y_test, target_names, model = load_and_train()

st.sidebar.header("Sample Selection")
index = st.sidebar.slider("Pick a sample index", 0, len(X_test)-1, 0)

sample = X_test.iloc[[index]]
prediction = model.predict(sample)[0]
prediction_proba = model.predict_proba(sample)[0]

st.sidebar.markdown("---")
st.sidebar.markdown("**Sample Information:**")
st.sidebar.write(f"**Predicted:** {target_names[prediction]}")
st.sidebar.write(f"**Confidence:** {prediction_proba[prediction]:.3f}")

col1, col2 = st.columns(2)

with col1:
    st.subheader("🔮 Model Prediction")
    st.write(f"The model predicts this is **{target_names[prediction]}**")
    
    st.subheader("📊 Sample Features")
    st.dataframe(sample.T, use_container_width=True)

with col2:
    st.subheader("📈 Feature Importance (Global)")
    feature_importance = pd.DataFrame({
        'feature': X.columns,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=True)
    
    fig, ax = plt.subplots(figsize=(8,6))
    ax.barh(feature_importance['feature'], feature_importance['importance'])
    ax.set_xlabel("Importance")
    ax.set_title("Global Feature Importance")
    plt.tight_layout()
    st.pyplot(fig)

st.subheader("🎯 SHAP Explanation")
st.write("Feature importance for this specific prediction:")

try:
    import shap
    shap.initjs()
    
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(sample)
    
    if isinstance(shap_values, list):
        shap_vals_for_sample = shap_values[prediction][0]
    else:
        shap_vals_for_sample = shap_values[0]
    
    fig, ax = plt.subplots(figsize=(10,6))
    colors = ['green' if val>0 else 'red' for val in shap_vals_for_sample]
    ax.barh(X.columns, shap_vals_for_sample, color=colors)
    ax.set_xlabel("SHAP Value")
    ax.set_title("SHAP Feature Importance for This Prediction")
    ax.axvline(0, color='black', linestyle='--', alpha=0.3)
    plt.tight_layout()
    st.pyplot(fig)
    
    st.write("**SHAP Values:**")
    for feature, val in zip(X.columns, shap_vals_for_sample):
        color = "🟢" if val>0 else "🔴"
        st.write(f"{color} **{feature}**: {val:.4f}")
    
except ImportError:
    st.error("SHAP is not installed. Install via: pip install shap")
except Exception as e:
    st.error(f"Error with SHAP: {str(e)}")
    st.write("Showing fallback: model feature importance")
    fig, ax = plt.subplots(figsize=(10,6))
    ax.barh(X.columns, model.feature_importances_)
    ax.set_xlabel("Importance")
    ax.set_title("Model Feature Importance (Fallback)")
    plt.tight_layout()
    st.pyplot(fig)

with st.expander("📋 Model Details"):
    st.write("**Dataset:** Iris (150 samples, 4 features)")
    st.write("**Model:** Random Forest Classifier (100 trees)")
    st.write("**Features:** Sepal Length, Sepal Width, Petal Length, Petal Width")
    st.write("**Classes:** Setosa, Versicolor, Virginica")
    
    y_pred = model.predict(X_test)
    accuracy = np.mean(y_pred == y_test)
    st.write(f"**Accuracy:** {accuracy:.3f}")

st.markdown("---")
st.markdown("**💡 How to interpret:**")
st.markdown("- 🟢 Green bars: Features push toward predicted class")
st.markdown("- 🔴 Red bars: Features push against predicted class")
st.markdown("- Larger absolute values: More important features")
