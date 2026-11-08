// Convert the entered height when the user changes units.
const units = document.getElementById("preferred-units");
const height = document.getElementById("height");
const heightUnit = document.getElementById("height-unit");
let previousUnits = units.value;
units.addEventListener("change", () => {
    if (height.value !== "" && Number.isFinite(height.valueAsNumber) && units.value !==
        previousUnits) {
        const converted = units.value === "metric" ?
            height.valueAsNumber * 2.54 :
            height.valueAsNumber / 2.54;
        height.value = Number(converted.toFixed(10));
    }
    heightUnit.textContent = units.value === "metric" ? "cm" : "inches";
    previousUnits = units.value;
});
