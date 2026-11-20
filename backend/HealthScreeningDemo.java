import java.util.Scanner;

public class HealthScreeningDemo {

    public static void main(String[] args) {

        Scanner sc = new Scanner(System.in);

        System.out.println("==================================");
        System.out.println(" BLOOD DONOR HEALTH SCREENING");
        System.out.println("==================================");

        System.out.print("Enter Heart Rate (BPM): ");
        double heartRate = sc.nextDouble();

        System.out.print("Enter Body Temperature (C): ");
        double temperature = sc.nextDouble();

        System.out.print("Enter SpO2 Level (%): ");
        double spo2 = sc.nextDouble();

        if (heartRate < 30 || heartRate > 220 ||
            temperature < 30 || temperature > 45 ||
            spo2 < 50 || spo2 > 100) {

            System.out.println("\nInvalid input readings.");
            sc.close();
            return;
        }

        System.out.println("\n========== SCREENING REPORT ==========");

        System.out.println("Heart Rate  : " + heartRate + " BPM");
        System.out.println("Temperature : " + temperature + " C");
        System.out.println("SpO2 Level  : " + spo2 + " %");

        boolean alert = false;

        System.out.println("\n========== SCREENING RESULT ==========");

        if (heartRate < 60 || heartRate > 100) {
            System.out.println("WARNING: Heart rate outside general resting range.");
            alert = true;
        }

        if (temperature >= 38.0) {
            System.out.println("WARNING: High body temperature.");
            alert = true;
        }

        if (spo2 < 95) {
            System.out.println("WARNING: Low oxygen saturation.");
            alert = true;
        }

        if (alert) {
            System.out.println("\nSTATUS: NEEDS MEDICAL REVIEW");
            System.out.println("Professional assessment is required.");
        } else {
            System.out.println("\nSTATUS: NO BASIC SCREENING ALERTS");
            System.out.println("Proceed to professional donor assessment.");
        }

        System.out.println("\nNote: This is a prototype only.");
        System.out.println("It does not medically approve a donor.");

        sc.close();
    }
}

