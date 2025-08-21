package com.example

object Main extends App {
  val calculator = new Calculator()
  
  println(s"5 + 3 = ${calculator.add(5, 3)}")
  println(s"10 - 4 = ${calculator.subtract(10, 4)}")
  println(s"6 * 7 = ${calculator.multiply(6, 7)}")
  
  calculator.divide(10, 2) match {
    case Some(result) => println(s"10 / 2 = $result")
    case None => println("Division by zero!")
  }
}

trait Shape {
  def area: Double
  def perimeter: Double
}

case class Circle(radius: Double) extends Shape {
  def area: Double = Math.PI * radius * radius
  def perimeter: Double = 2 * Math.PI * radius
}

case class Rectangle(width: Double, height: Double) extends Shape {
  def area: Double = width * height
  def perimeter: Double = 2 * (width + height)
}