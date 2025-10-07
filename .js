import java.util.*;
public class main {
    public static void main (String args[]){
        Scanner sc=new Scanner(System.in);
        String name=sc.nextLine();
        int id=sc.nextInt();
        int borrow=sc.nextInt();
        
        lib(name,id,borrow);
    }
    public static void lib(String name,int id , int borrow){
        try {
            if (borrow <0 || name.length()<1 || name.length()>50){
                System.out.println("Invalid input");
                return;
            }
            if (id<10000 || id >99999){
                System.out.println("Invalid Input");
                return;
            }
            System.out.println("Member Name: "+name);
            System.out.println("Membership ID: "+id);
            System.out.println("Books Borrowed: "+borrow);
            if(borrow >=10){
                System.out.println("Status: Active Reader");
            }
            else if(borrow >=5 && borrow <=9){
                System.out.println("Status: Moderate Reader");
            }
            else if(borrow >=1 && borrow <=4){
                System.out.println("Status: Casual Reader");
            }
            else if (borrow ==0){
                System.out.println("Status: Inactive");
            }
            else{
                System.out.println("Invalid Input");
            }
            
        }
        catch(Exception e){
            System.out.println("Invalid Input");
        }
    }

}