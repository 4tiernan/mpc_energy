## Controller Options
The MPC Energy App has three available control options, Safe Mode, RBC and MPC. The specific behaviour of each controller has been documented below:

### Safe Mode
Safe Mode is less of a controller and more just a state to put the battery system into to try and minimise grid interaction and thus cost. This mode will not export power at all and will only import when the battery is flat. This mode should only be used when one of the other controllers is unsuitable (not suffient load data yet or unexplained weird behaviour). IE, if it ain't working right, use safe mode to reduce avoidable grid interaction. 

### RBC 
RBC stands for Rule Based Control. This controller uses a series of IF logic based conditions to determine the most suitable control mode. This controller will not import power unless the battery is flat but will export power. However, it will aim to only sell excess power meaning it will always plan to keep enough energy stored in the battery to last the night. Given these simple conditions it's behaviour is very predictable and relatively safe, however, it does struggle when solar is insufficent to cover your daily load as it will only import power once the battery is flat. 




## Battery Control Modes
