// Hold selected foods until the user saves the list.
let foodsToLog = [];
// Add the selected food and amount to the list.
document.querySelectorAll(".add-food-button").forEach(function(button) {
    button.addEventListener("click", function() {
        const row = button.closest("tr");
        const foodId = button.dataset.foodId;
        const foodName = row
            .querySelector(".food-name")
            .innerText
            .trim();
        const amountInput = row.querySelector(".food-amount");
        const unitSelect = row.querySelector(".food-unit");
        const amount = amountInput.value;
        const unit = unitSelect.value;
        if (!amount || parseFloat(amount) <= 0) {
            alert("Please enter a valid amount.");
            return;
        }
        if (!unit) {
            alert("Please select a unit.");
            return;
        }
        const food = {
            food_item_id: foodId,
            name: foodName,
            amount: amount,
            unit: unit
        };
        foodsToLog.push(food);
        renderFoodList();
    });
});
// Remove a food from the unsaved list.
function removeFood(index) {
    foodsToLog.splice(index, 1);
    renderFoodList();
}
// Refresh the preview and the fields submitted to the server.
function renderFoodList() {
    const table = document.getElementById("food-list-table");
    const tableBody = document.getElementById("food-list-body");
    const emptyMessage = document.getElementById(
        "empty-list-message"
    );
    const hiddenInputs = document.getElementById(
        "hidden-food-inputs"
    );
    const logAllButton = document.getElementById(
        "log-all-button"
    );
    // Clear old rows and hidden inputs
    tableBody.innerHTML = "";
    hiddenInputs.innerHTML = "";
    // Disable saving when the list is empty.
    if (foodsToLog.length === 0) {
        table.style.display = "none";
        emptyMessage.style.display = "block";
        logAllButton.disabled = true;
        return;
    }
    // Show the queued foods and enable saving.
    table.style.display = "table";
    emptyMessage.style.display = "none";
    logAllButton.disabled = false;
    foodsToLog.forEach(function(food, index) {
        // Build one preview row for each selected food.
        const row = document.createElement("tr");
        const nameCell = document.createElement("td");
        nameCell.textContent = food.name;
        const amountCell = document.createElement("td");
        amountCell.textContent = food.amount;
        const unitCell = document.createElement("td");
        unitCell.textContent = food.unit;
        const removeCell = document.createElement("td");
        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.textContent = "Remove";
        removeButton.addEventListener("click", function() {
            removeFood(index);
        });
        removeCell.appendChild(removeButton);
        row.appendChild(nameCell);
        row.appendChild(amountCell);
        row.appendChild(unitCell);
        row.appendChild(removeCell);
        tableBody.appendChild(row);
        // Submit matching food IDs, amounts, and units together.
        const foodIdInput = document.createElement("input");
        foodIdInput.type = "hidden";
        foodIdInput.name = "food_item_id";
        foodIdInput.value = food.food_item_id;
        const amountInput = document.createElement("input");
        amountInput.type = "hidden";
        amountInput.name = "amount";
        amountInput.value = food.amount;
        const unitInput = document.createElement("input");
        unitInput.type = "hidden";
        unitInput.name = "unit";
        unitInput.value = food.unit;
        hiddenInputs.appendChild(foodIdInput);
        hiddenInputs.appendChild(amountInput);
        hiddenInputs.appendChild(unitInput);
    });
}
// Filter saved foods by the search text.
const foodSearch = document.getElementById("food-search");
if (foodSearch) {
    foodSearch.addEventListener("input", function() {
        const searchText = foodSearch.value
            .toLowerCase()
            .trim();
        document
            .querySelectorAll(".saved-food-row")
            .forEach(function(row) {
                const rowText = row
                    .innerText
                    .toLowerCase();
                if (rowText.includes(searchText)) {
                    row.style.display = "";
                } else {
                    row.style.display = "none";
                }
            });
    });
}
